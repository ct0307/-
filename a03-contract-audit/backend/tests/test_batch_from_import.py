"""从智能收件箱创建审查批次的契约测试。"""

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints import batches
from app.db.session import Base
from app.models.models import (
    AuditBatch,
    AuditBatchItem,
    AuditLog,
    Contract,
    ImportBatch,
    ImportBatchItem,
    User,
)
from app.schemas.batch import BatchFromImportRequest
from app.tasks import audit_tasks
from app.tasks.audit_tasks import run_contract_audit


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _user(db: Session) -> User:
    user = User(
        username="legal",
        password_hash="not-used",
        role="legal",
        department="法务部",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _import_item(
    db: Session,
    user: User,
    *,
    filename: str,
    contract_type: str,
    status: str = "ready",
) -> ImportBatchItem:
    batch = ImportBatch(
        owner_id=user.id,
        idempotency_key=f"import-{filename}",
        status="ready" if status == "ready" else "needs_attention",
        total=1,
        ready=1 if status == "ready" else 0,
    )
    contract = Contract(
        filename=filename,
        storage_path=f"storage/{filename}",
        contract_type=contract_type,
        department=user.department,
        uploaded_by=user.id,
        status="parsed",
    )
    item = ImportBatchItem(filename=filename, contract=contract, status=status)
    batch.items.append(item)
    db.add(batch)
    db.commit()
    db.refresh(item)
    return item


def test_create_audit_batch_from_ready_mixed_import_items(monkeypatch):
    db = _session()
    legal = _user(db)
    purchase_item = _import_item(
        db,
        legal,
        filename="采购合同.txt",
        contract_type="采购合同",
    )
    software_item = _import_item(
        db,
        legal,
        filename="开发协议.txt",
        contract_type="软件开发外包合同",
    )
    dispatched: list[tuple[int, list[str]]] = []
    monkeypatch.setattr(
        batches,
        "_dispatch_item",
        lambda item, dimensions: dispatched.append((item.id, dimensions)) or f"task-{item.id}",
    )

    result = batches.create_batch_from_import(
        body=BatchFromImportRequest(
            import_item_ids=[purchase_item.id, software_item.id],
            dimensions=["payment", "legal", "legal"],
        ),
        idempotency_key="audit-from-import-1",
        db=db,
        user=legal,
    )

    assert result.total == 2
    saved_types = [db.get(Contract, item.contract_id).contract_type for item in result.items]
    assert saved_types == ["采购合同", "软件开发外包合同"]
    assert [db.get(ImportBatchItem, item_id).status for item_id in [purchase_item.id, software_item.id]] == [
        "auditing",
        "auditing",
    ]
    assert all(item.import_item_id for item in db.query(AuditBatchItem).all())
    assert [dimensions for _, dimensions in dispatched] == [["legal", "payment"]] * 2
    log = db.query(AuditLog).filter(AuditLog.action == "batch_create_from_import").one()
    assert log.target == f"batch:{result.id}"


def test_batch_from_import_rejects_non_ready_item():
    db = _session()
    legal = _user(db)
    awaiting_item = _import_item(
        db,
        legal,
        filename="待确认.txt",
        contract_type="",
        status="awaiting_confirmation",
    )

    with pytest.raises(HTTPException) as error:
        batches.create_batch_from_import(
            BatchFromImportRequest(import_item_ids=[awaiting_item.id], dimensions=[]),
            "not-ready-key",
            db,
            legal,
        )

    assert error.value.status_code == 409
    assert error.value.detail["code"] == "IMPORT_ITEM_NOT_READY"


def test_batch_from_import_rejects_reused_key_with_different_items(monkeypatch):
    db = _session()
    legal = _user(db)
    first_item = _import_item(db, legal, filename="一.txt", contract_type="采购合同")
    second_item = _import_item(db, legal, filename="二.txt", contract_type="租赁合同")
    monkeypatch.setattr(batches, "_dispatch_item", lambda *_args: "task")

    batches.create_batch_from_import(
        BatchFromImportRequest(import_item_ids=[first_item.id], dimensions=[]),
        "same-audit-key",
        db,
        legal,
    )

    with pytest.raises(HTTPException) as error:
        batches.create_batch_from_import(
            BatchFromImportRequest(import_item_ids=[second_item.id], dimensions=[]),
            "same-audit-key",
            db,
            legal,
        )

    assert error.value.status_code == 409


def test_audit_task_writes_import_item_status_back(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        legal = _user(db)
        source_item = _import_item(
            db,
            legal,
            filename="成功.txt",
            contract_type="采购合同",
            status="auditing",
        )
        audit_batch = AuditBatch(
            owner_id=legal.id,
            department=legal.department,
            idempotency_key="write-back-success",
        )
        audit_item = AuditBatchItem(
            contract_id=source_item.contract_id,
            import_item_id=source_item.id,
            filename=source_item.filename,
        )
        audit_batch.items.append(audit_item)
        db.add(audit_batch)
        db.commit()
        contract_id, audit_item_id, source_item_id = (
            source_item.contract_id,
            audit_item.id,
            source_item.id,
        )

    def fake_run_audit(session, _contract, **kwargs):
        item = session.get(AuditBatchItem, kwargs["batch_item_id"])
        item.status = "done"
        item.finished_at = datetime.now(timezone.utc)
        session.commit()
        return {"risk_count": 0, "cross_checks": []}

    monkeypatch.setattr(audit_tasks, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(audit_tasks, "run_audit", fake_run_audit)

    result = run_contract_audit.run(contract_id, ["legal"], audit_item_id)

    with Session(engine) as db:
        assert result["status"] == "done"
        assert db.get(ImportBatchItem, source_item_id).status == "done"


def test_failed_audit_returns_import_item_to_ready(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        legal = _user(db)
        source_item = _import_item(
            db,
            legal,
            filename="失败.txt",
            contract_type="采购合同",
            status="auditing",
        )
        audit_batch = AuditBatch(
            owner_id=legal.id,
            department=legal.department,
            idempotency_key="write-back-failure",
        )
        audit_item = AuditBatchItem(
            contract_id=source_item.contract_id,
            import_item_id=source_item.id,
            filename=source_item.filename,
        )
        audit_batch.items.append(audit_item)
        db.add(audit_batch)
        db.commit()
        contract_id, audit_item_id, source_item_id = (
            source_item.contract_id,
            audit_item.id,
            source_item.id,
        )

    monkeypatch.setattr(audit_tasks, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(
        audit_tasks,
        "run_audit",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("audit failed")),
    )

    with pytest.raises(RuntimeError):
        run_contract_audit.run(contract_id, ["legal"], audit_item_id)

    with Session(engine) as db:
        assert db.get(ImportBatchItem, source_item_id).status == "ready"
