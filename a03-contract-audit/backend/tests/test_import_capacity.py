from io import BytesIO
from pathlib import Path
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import time

import pytest
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.testclient import TestClient
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints import batches, contracts, imports
from app.core.config import settings, Settings
from pydantic import ValidationError
from app.db.session import Base, get_db
from app.models.models import AuditLog, Contract, ImportAppendRequest, ImportBatch, ImportBatchItem, User
from app.api.deps import get_current_user


def _file(name: str, size: int) -> UploadFile:
    return UploadFile(filename=name, file=BytesIO(b"x" * size))


def test_upload_limits_have_one_source_of_truth():
    assert settings.MAX_UPLOAD_MB == 50
    assert settings.MAX_BATCH_FILES == 200
    assert settings.MAX_BATCH_MB == 500
    assert settings.max_file_size_bytes == 50 * 1024 * 1024
    assert settings.max_batch_size_bytes == 500 * 1024 * 1024
    assert imports.get_import_limits(None)["max_batch_files"] == settings.MAX_BATCH_FILES


@pytest.mark.parametrize("field", ["MAX_UPLOAD_MB", "MAX_BATCH_FILES", "MAX_BATCH_MB"])
@pytest.mark.parametrize("value", [0, -1])
def test_capacity_configuration_rejects_non_positive_values(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, APP_ENV="dev", **{field: value})


def test_new_batch_rejects_total_size_over_the_batch_limit_with_stable_code(monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_MB", 10)
    monkeypatch.setattr(settings, "MAX_BATCH_MB", 1)
    with pytest.raises(HTTPException) as error:
        batches._validate_uploads([_file("a.txt", 600 * 1024), _file("b.txt", 600 * 1024)])

    assert error.value.status_code == 413
    assert error.value.detail["code"] == "BATCH_TOO_LARGE"


def test_legacy_batch_upload_has_the_same_batch_count_limit():
    with pytest.raises(HTTPException) as error:
        contracts._validate_batch_capacity([_file("a.txt", 1)] * (settings.MAX_BATCH_FILES + 1))

    assert error.value.status_code == 413
    assert error.value.detail["code"] == "BATCH_TOO_LARGE"


def test_nginx_body_limit_covers_a_valid_maximum_batch():
    nginx = Path("../frontend/nginx.conf").read_text(encoding="utf-8")
    assert "client_max_body_size 520m" in nginx


@pytest.fixture
def context(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "MAX_UPLOAD_MB", 1)
    monkeypatch.setattr(settings, "MAX_BATCH_MB", 1)
    monkeypatch.setattr(settings, "FILE_ENCRYPT_KEY", "")
    monkeypatch.setattr(imports, "_dispatch_import_item", lambda _id: "test-task")
    with Session(engine) as db:
        user = User(username="capacity-user", password_hash="unused", role="legal", department="法务部")
        db.add(user)
        db.commit()
        yield db, user, tmp_path


def _create(context, files):
    db, user, _ = context
    return imports.create_import(files, "capacity-create", user.department, db, user)


def test_import_total_rejection_does_not_persist_anything(context):
    db, _, directory = context
    with pytest.raises(HTTPException) as error:
        _create(context, [_file("a.txt", 600 * 1024), _file("b.txt", 600 * 1024)])
    assert error.value.detail["code"] == "BATCH_TOO_LARGE"
    assert db.query(ImportBatch).count() == db.query(Contract).count() == db.query(AuditLog).count() == 0
    assert list(directory.iterdir()) == []


def test_new_import_keeps_oversized_file_failure_isolated(context, monkeypatch):
    monkeypatch.setattr(settings, "MAX_BATCH_MB", 3)
    result = _create(context, [_file("big.txt", 1024 * 1024 + 1), _file("small.txt", 10)])
    assert result.items[0].error_code == "FILE_TOO_LARGE"
    assert result.items[0].contract_id is None
    assert result.items[1].status == "queued"
    assert context[0].query(Contract).count() == 1


def test_append_uses_original_plaintext_sizes_at_exact_boundary(context, monkeypatch):
    db, user, _ = context
    monkeypatch.setattr(settings, "FILE_ENCRYPT_KEY", Fernet.generate_key().decode())
    result = _create(context, [_file("a.txt", 600 * 1024)])
    appended = imports.append_import_items(result.id, [_file("b.txt", 424 * 1024)], "capacity-append", db, user)
    assert appended.total == 2
    assert appended.failed == 0
    metadata = db.query(AuditLog).filter_by(action="import_item_capacity").all()
    assert sorted(json.loads(entry.detail)["plaintext_bytes"] for entry in metadata) == [424 * 1024, 600 * 1024]


def test_append_counts_failed_upload_original_bytes(context):
    db, user, _ = context
    result = _create(context, [_file("a.exe", 600 * 1024)])
    with pytest.raises(HTTPException) as error:
        imports.append_import_items(result.id, [_file("b.txt", 600 * 1024)], "capacity-append", db, user)
    assert error.value.detail["code"] == "BATCH_TOO_LARGE"
    assert db.query(ImportBatchItem).count() == 1


def test_append_legacy_encrypted_file_falls_back_to_decryption(context, monkeypatch):
    db, user, _ = context
    monkeypatch.setattr(settings, "FILE_ENCRYPT_KEY", Fernet.generate_key().decode())
    result = _create(context, [_file("a.txt", 600 * 1024)])
    db.query(AuditLog).filter_by(action="import_item_capacity").delete()
    db.commit()
    appended = imports.append_import_items(result.id, [_file("b.txt", 424 * 1024)], "legacy-append", db, user)
    assert appended.total == 2


@pytest.mark.parametrize("kind", ["missing_file", "failed_without_file", "invalid_metadata"])
def test_unknown_existing_capacity_rejects_append_conservatively(context, kind):
    db, user, directory = context
    batch = ImportBatch(owner_id=user.id, idempotency_key="legacy-unknown", department=user.department)
    item = ImportBatchItem(filename="a.txt", status="failed")
    if kind != "failed_without_file":
        item.contract = Contract(filename="a.txt", storage_path=str(directory / "missing.txt"), uploaded_by=user.id, department=user.department)
    batch.items.append(item)
    db.add(batch)
    db.flush()
    if kind == "invalid_metadata":
        db.add(AuditLog(user_id=user.id, action="import_item_capacity", target=f"import-item:{item.id}", detail='{"plaintext_bytes": -1}'))
    db.commit()
    with pytest.raises(HTTPException) as error:
        imports.append_import_items(batch.id, [_file("b.txt", 10)], "unknown-append", db, user)
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "IMPORT_BATCH_CAPACITY_UNKNOWN"
    assert db.query(ImportBatchItem).count() == 1
    assert list(directory.iterdir()) == []


def test_append_replay_bypasses_new_capacity_count(context, monkeypatch):
    db, user, _ = context
    result = _create(context, [_file("a.txt", 600 * 1024)])
    imports.append_import_items(result.id, [_file("b.txt", 424 * 1024)], "replay-append", db, user)
    monkeypatch.setattr(settings, "MAX_BATCH_FILES", 1)
    replay = imports.append_import_items(result.id, [_file("b.txt", 424 * 1024)], "replay-append", db, user)
    assert replay.total == 2
    assert db.query(ImportBatchItem).count() == 2


def test_limits_endpoint_is_authenticated_and_uses_current_config(context, monkeypatch):
    app = FastAPI()
    app.include_router(imports.router, prefix="/imports")
    db, user, _ = context
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        assert client.get("/imports/limits").status_code == 401
        app.dependency_overrides[get_current_user] = lambda: user
        monkeypatch.setattr(settings, "MAX_UPLOAD_MB", 7)
        monkeypatch.setattr(settings, "MAX_BATCH_FILES", 9)
        monkeypatch.setattr(settings, "MAX_BATCH_MB", 13)
        response = client.get("/imports/limits")
        assert response.status_code == 200
        assert response.json() == {"max_file_mb": 7, "max_batch_files": 9, "max_batch_mb": 13}


def test_legacy_single_upload_returns_stable_file_capacity_code(context):
    db, user, _ = context
    with pytest.raises(HTTPException) as error:
        contracts.upload_contract(_file("large.txt", 1024 * 1024 + 1), "采购合同", None, db, user)
    assert error.value.status_code == 413
    assert error.value.detail["code"] == "FILE_TOO_LARGE"


def test_batch_count_limit_reads_configuration_dynamically(monkeypatch):
    monkeypatch.setattr(settings, "MAX_BATCH_FILES", 2)
    with pytest.raises(HTTPException) as error:
        batches._validate_uploads([_file("a.txt", 1)] * 3)
    assert error.value.status_code == 413
    assert error.value.detail["code"] == "BATCH_TOO_LARGE"


def test_legacy_batch_upload_keeps_oversized_file_failure_isolated(context, monkeypatch):
    db, user, _ = context
    monkeypatch.setattr(settings, "MAX_BATCH_MB", 3)
    results = contracts.batch_upload_contracts([_file("big.txt", 1024 * 1024 + 1), _file("normal.txt", 20)], "采购合同", db, user)
    assert results[0]["status"] == "failed"
    assert results[0]["error_code"] == "FILE_TOO_LARGE"
    assert results[1]["status"] == "success"
    assert db.query(Contract).count() == 1


@pytest.mark.parametrize("kind", ["empty_storage", "wrong_hash"])
def test_legacy_unverifiable_file_bytes_reject_append(context, kind):
    db, user, directory = context
    path = directory / "original.txt"
    path.write_bytes(b"" if kind == "empty_storage" else b"modified")
    batch = ImportBatch(owner_id=user.id, idempotency_key="legacy-unverifiable", department=user.department)
    batch.items.append(ImportBatchItem(filename="original.txt", contract=Contract(filename="original.txt", storage_path=str(path), uploaded_by=user.id, department=user.department, content_sha256="0" * 64 if kind == "wrong_hash" else None), status="queued"))
    db.add(batch)
    db.commit()
    with pytest.raises(HTTPException) as error:
        imports.append_import_items(batch.id, [_file("b.txt", 10)], "unverifiable-append", db, user)
    assert error.value.detail["code"] == "IMPORT_BATCH_CAPACITY_UNKNOWN"


def test_append_count_overflow_uses_same_status_and_code_as_new_upload(context, monkeypatch):
    db, user, _ = context
    monkeypatch.setattr(settings, "MAX_BATCH_FILES", 1)
    result = _create(context, [_file("a.txt", 1)])
    with pytest.raises(HTTPException) as error:
        imports.append_import_items(result.id, [_file("b.txt", 1)], "count-overflow", db, user)
    assert error.value.status_code == 413
    assert error.value.detail["code"] == "BATCH_TOO_LARGE"


def test_sqlite_concurrent_append_serializes_capacity_check_and_write(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'capacity-concurrent.db').as_posix()}", connect_args={"check_same_thread": False, "timeout": 5})
    Base.metadata.create_all(engine)
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "MAX_BATCH_MB", 1)
    monkeypatch.setattr(settings, "FILE_ENCRYPT_KEY", "")
    with Session(engine) as db:
        user = User(username="capacity-owner", password_hash="unused", role="legal", department="法务部")
        db.add(user)
        db.commit()
        result = imports.create_import([_file("seed.exe", 1)], "concurrent-create", user.department, db, user)
        batch_id, user_id = result.id, user.id

    original = imports.existing_batch_bytes
    def slow_capacity_read(db, batch):
        size = original(db, batch)
        # 放大读取与提交之间的真实竞争窗口，不在持锁区域设置线程屏障。
        time.sleep(0.15)
        return size
    monkeypatch.setattr(imports, "existing_batch_bytes", slow_capacity_read)
    entry = Barrier(2)
    def append(index):
        with Session(engine) as db:
            user = db.get(User, user_id)  # 模拟认证已开启请求会话事务。
            entry.wait(timeout=5)
            try:
                imports.append_import_items(batch_id, [_file(f"append-{index}.exe", 600 * 1024)], f"concurrent-append-{index}", db, user)
                return "accepted"
            except HTTPException as error:
                assert error.status_code == 413
                assert error.detail["code"] == "BATCH_TOO_LARGE"
                return "rejected"
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(append, range(2)))
    assert sorted(outcomes) == ["accepted", "rejected"]
    with Session(engine) as db:
        assert db.query(ImportBatchItem).filter_by(batch_id=batch_id).count() == 2
        assert db.query(ImportAppendRequest).filter_by(batch_id=batch_id).count() == 1
        total = sum(json.loads(row.detail)["plaintext_bytes"] for row in db.query(AuditLog).filter_by(action="import_item_capacity"))
        assert total == 1 + 600 * 1024 <= settings.max_batch_size_bytes


@pytest.mark.parametrize("reason", ["replay", "overflow", "unauthorized"])
def test_sqlite_append_releases_transaction_on_replay_and_rejection(context, reason, monkeypatch):
    db, owner, _ = context
    result = _create(context, [_file("first.exe", 1)])
    files = [_file("next.exe", 600 * 1024)]
    if reason == "replay":
        imports.append_import_items(result.id, files, "released-append", db, owner)
        files = [_file("next.exe", 600 * 1024)]
    elif reason == "overflow":
        monkeypatch.setattr(settings, "MAX_BATCH_FILES", 1)
    else:
        peer = User(username="capacity-peer", password_hash="unused", role="legal", department=owner.department)
        db.add(peer)
        db.commit()
        owner = peer
    if reason == "replay":
        replay = imports.append_import_items(result.id, files, "released-append", db, owner)
        assert replay.total == 2
    else:
        with pytest.raises(HTTPException) as error:
            imports.append_import_items(result.id, files, "released-append", db, owner)
        assert error.value.status_code == (413 if reason == "overflow" else 403)
    assert not db.in_transaction()
