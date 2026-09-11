"""可恢复合同导入 API 测试。"""

from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints import imports
from app.core.config import settings
from app.db.session import Base
from app.models.models import AuditLog, Contract, ImportBatch, ImportBatchItem, User
from app.schemas.import_batch import ConfirmImportItem


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _user(db: Session, *, username="legal", role="legal", department="法务部") -> User:
    user = User(username=username, password_hash="x", role=role, department=department)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _file(name: str, content: bytes) -> UploadFile:
    return UploadFile(filename=name, file=BytesIO(content))


def test_create_import_keeps_valid_files_when_one_file_is_invalid(monkeypatch, tmp_path):
    db = _session()
    legal = _user(db)
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(imports, "_dispatch_import_item", lambda _item_id: "task-1")

    result = imports.create_import(
        files=[_file("采购合同.txt", "采购设备".encode()), _file("病毒.exe", b"bad")],
        idempotency_key="mixed-import-1",
        department="法务部",
        db=db,
        user=legal,
    )

    assert result.total == 2
    assert [item.status for item in result.items] == ["queued", "failed"]
    assert result.items[1].error_code == "UNSUPPORTED_FILE_TYPE"
    assert db.query(Contract).count() == 1


def test_create_import_is_idempotent_per_owner(monkeypatch, tmp_path):
    db = _session()
    legal = _user(db)
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(imports, "_dispatch_import_item", lambda _item_id: "task-1")

    first = imports.create_import([_file("合同.txt", b"body")], "stable-key", "法务部", db, legal)
    second = imports.create_import([_file("合同.txt", b"body")], "stable-key", "法务部", db, legal)

    assert second.id == first.id
    assert db.query(ImportBatch).count() == 1
    assert db.query(Contract).count() == 1


def test_get_import_rejects_an_unrelated_user():
    db = _session()
    owner = _user(db, username="owner", department="法务部")
    other = _user(db, username="other", role="business", department="采购中心")
    batch = ImportBatch(owner_id=owner.id, idempotency_key="private-import")
    db.add(batch)
    db.commit()

    with pytest.raises(HTTPException) as error:
        imports.get_import(batch.id, db=db, user=other)

    assert error.value.status_code == 403


def test_confirm_retry_remove_and_delete_have_distinct_semantics(monkeypatch, tmp_path):
    db = _session()
    legal = _user(db)
    batch = ImportBatch(owner_id=legal.id, idempotency_key="actions", total=3)
    contract = Contract(
        filename="待确认.txt",
        storage_path=str(tmp_path / "draft.txt"),
        uploaded_by=legal.id,
        department=legal.department,
        status="parsed",
    )
    batch.items.extend([
        ImportBatchItem(filename=contract.filename, contract=contract, status="awaiting_confirmation"),
        ImportBatchItem(filename="解析失败.pdf", contract=Contract(
            filename="解析失败.pdf", storage_path=str(tmp_path / "failed.pdf"),
            uploaded_by=legal.id, department=legal.department,
        ), status="failed", error_code="PARSE_FAILED"),
        ImportBatchItem(filename="病毒.exe", status="failed", error_code="UNSUPPORTED_FILE_TYPE"),
    ])
    db.add(batch)
    db.commit()
    confirm_id, parse_failed_id, upload_failed_id = [item.id for item in batch.items]
    monkeypatch.setattr(imports, "_dispatch_import_item", lambda _item_id: "task-retry")

    confirmed = imports.confirm_item(
        batch.id,
        confirm_id,
        ConfirmImportItem(contract_type="采购合同", department="法务部"),
        db,
        legal,
    )
    assert confirmed.status == "ready"
    assert db.get(Contract, contract.id).type_confirmed_by == legal.id

    retried = imports.retry_item(batch.id, parse_failed_id, db, legal)
    assert retried.status == "queued"

    imports.remove_failed_record(batch.id, upload_failed_id, db, legal)
    assert db.get(ImportBatchItem, upload_failed_id) is None

    deleted = imports.delete_contract_draft(batch.id, parse_failed_id, db, legal)
    assert deleted.status == "deleted"
    failed_contract = db.get(ImportBatchItem, parse_failed_id).contract
    assert failed_contract.deleted_at is not None
    assert db.query(AuditLog).filter(AuditLog.action == "contract_draft_delete").count() == 1


def test_create_import_isolates_one_invalid_file_in_a_fifty_two_file_batch(monkeypatch, tmp_path):
    db = _session()
    legal = _user(db)
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(imports, "_dispatch_import_item", lambda item_id: f"task-{item_id}")
    samples = [
        ("采购", "采购服务器设备"),
        ("开发", "交付软件源代码"),
        ("劳动", "约定劳动关系与试用期"),
        ("租赁", "出租方与承租方约定租赁期限"),
        ("扫描", "双方经协商一致订立本文件"),
    ]
    files = [
        _file(f"{label}合同-{index:02d}.txt", text.encode("utf-8"))
        for index in range(51)
        for label, text in [samples[index % len(samples)]]
    ]
    files.append(_file("病毒.exe", b"bad"))

    result = imports.create_import(
        files=files,
        idempotency_key="fifty-two-import-files",
        department="法务部",
        db=db,
        user=legal,
    )

    assert result.total == 52
    assert len(result.items) == 52
    assert sum(item.contract_id is not None for item in result.items) == 51
    assert sum(item.error_code == "UNSUPPORTED_FILE_TYPE" for item in result.items) == 1
    assert db.query(Contract).count() == 51
