"""异步批次 API 与任务调度契约。"""
from io import BytesIO
from inspect import signature
from datetime import datetime, timedelta, timezone
import json

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints import batches
from app.core.config import settings
from app.db.session import Base
from app.models.models import AuditBatch, AuditBatchItem, Contract, User
from app.schemas.batch import BatchOut
from app.tasks import audit_tasks
from app.tasks.audit_tasks import run_contract_audit
from app.tasks.celery_app import celery_app


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _user(db: Session, *, username: str = "legal", department: str = "法务部") -> User:
    user = User(
        username=username,
        password_hash="not-used",
        role="legal",
        department=department,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _files(count: int) -> list[UploadFile]:
    return [
        UploadFile(filename=f"contract-{index}.txt", file=BytesIO("合同正文".encode("utf-8")))
        for index in range(count)
    ]


def test_create_batch_persists_fifty_items(monkeypatch, tmp_path):
    db = _session()
    user = _user(db)
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(batches, "_dispatch_item", lambda _item, _dimensions: "task-1")

    result = batches.create_batch(
        files=_files(50),
        idempotency_key="request-50",
        contract_type="采购合同",
        dimensions=["legal"],
        db=db,
        user=user,
    )

    assert result.total == 50
    assert db.query(AuditBatchItem).count() == 50
    assert db.query(Contract).count() == 50
    assert len(list(tmp_path.iterdir())) == 50


def test_create_batch_persists_dimensions_for_recovery(monkeypatch, tmp_path):
    db = _session()
    user = _user(db)
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(batches, "_dispatch_item", lambda _item, _dimensions: "task-1")

    result = batches.create_batch(_files(1), "recoverable", "", ["legal", "payment"], db, user)
    saved = db.get(AuditBatch, result.id)

    assert saved is not None
    assert json.loads(saved.dimensions_json) == ["legal", "payment"]


def test_completed_batch_item_exposes_contract_review_quality(tmp_path):
    db = _session()
    user = _user(db)
    contract = Contract(
        filename="scan.pdf",
        storage_path=str(tmp_path / "scan.pdf"),
        department=user.department,
        uploaded_by=user.id,
        requires_review=True,
        ocr_confidence=0.42,
        review_reason="OCR 平均置信度低于 75%",
    )
    batch = AuditBatch(
        owner_id=user.id,
        department=user.department,
        idempotency_key="quality-fields",
        status="done",
        total=1,
        completed=1,
    )
    db.add_all([contract, batch])
    db.flush()
    batch.items.append(
        AuditBatchItem(
            contract_id=contract.id,
            filename=contract.filename,
            status="done",
        )
    )
    db.commit()

    payload = BatchOut.model_validate(batch).model_dump()
    item = payload["items"][0]

    assert item["status"] == "done"
    assert item["requires_review"] is True
    assert item["ocr_confidence"] == 0.42
    assert item["review_reason"] == "OCR 平均置信度低于 75%"


def test_create_batch_rejects_more_than_two_hundred_files(tmp_path):
    db = _session()
    user = _user(db)

    with pytest.raises(HTTPException) as exc_info:
        batches.create_batch(
            files=_files(201),
            idempotency_key="too-many",
            contract_type="",
            dimensions=[],
            db=db,
            user=user,
        )

    assert exc_info.value.status_code == 400
    assert list(tmp_path.iterdir()) == []


def test_create_batch_is_idempotent_for_same_owner(monkeypatch, tmp_path):
    db = _session()
    user = _user(db)
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(batches, "_dispatch_item", lambda _item, _dimensions: "task-1")
    files = _files(1)

    first = batches.create_batch(files, "same-request", "", [], db, user)
    second = batches.create_batch(files, "same-request", "", [], db, user)

    assert second.id == first.id
    assert db.query(AuditBatch).count() == 1
    assert db.query(Contract).count() == 1


def test_get_batch_rejects_other_department():
    db = _session()
    owner = _user(db)
    other = _user(db, username="other", department="财务部")
    batch = AuditBatch(owner_id=owner.id, department=owner.department, idempotency_key="scope")
    db.add(batch)
    db.commit()

    with pytest.raises(HTTPException) as exc_info:
        batches.get_batch(batch.id, db=db, user=other)

    assert exc_info.value.status_code == 403


def test_create_batch_cleans_files_when_database_flush_fails(monkeypatch, tmp_path):
    db = _session()
    user = _user(db)
    db.autoflush = False
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    real_flush = db.flush
    flush_count = 0

    def fail_after_first_file(*args, **kwargs):
        nonlocal flush_count
        flush_count += 1
        if flush_count == 2:
            raise RuntimeError("database unavailable")
        return real_flush(*args, **kwargs)

    monkeypatch.setattr(db, "flush", fail_after_first_file)

    with pytest.raises(HTTPException) as exc_info:
        batches.create_batch(_files(2), "rollback", "", [], db, user)

    assert exc_info.value.status_code == 500
    assert list(tmp_path.iterdir()) == []


def test_audit_task_accepts_dimensions_and_batch_item_id():
    params = signature(run_contract_audit.run).parameters

    assert "dimensions" in params
    assert "batch_item_id" in params


def test_audit_task_updates_batch_item_and_forwards_dimensions(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = _user(db)
        contract = Contract(
            filename="contract.txt",
            storage_path=str(tmp_path / "contract.txt"),
            contract_type="采购合同",
            department=user.department,
            uploaded_by=user.id,
        )
        batch = AuditBatch(owner_id=user.id, department=user.department, idempotency_key="worker-test")
        db.add_all([contract, batch])
        db.flush()
        item = AuditBatchItem(batch_id=batch.id, contract_id=contract.id, filename=contract.filename)
        db.add(item)
        db.commit()
        contract_id, item_id = contract.id, item.id

    captured: list[list[str]] = []

    def fake_run_audit(_db, _contract, dimensions=None):
        captured.append(dimensions or [])
        return {"risk_count": 0, "cross_checks": []}

    monkeypatch.setattr(audit_tasks, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(audit_tasks, "run_audit", fake_run_audit)

    result = run_contract_audit.run(contract_id, ["legal"], item_id)
    repeated = run_contract_audit.run(contract_id, ["finance"], item_id)

    with Session(engine) as db:
        saved = db.get(AuditBatchItem, item_id)
        assert saved is not None
        assert saved.status == "done"
        assert saved.finished_at is not None
    assert result["status"] == "done"
    assert repeated["status"] == "already_done"
    assert captured == [["legal"]]


def test_audit_task_does_not_duplicate_an_active_lease(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = _user(db)
        contract = Contract(
            filename="contract.txt",
            storage_path=str(tmp_path / "contract.txt"),
            department=user.department,
            uploaded_by=user.id,
        )
        batch = AuditBatch(owner_id=user.id, department=user.department, idempotency_key="active-lease")
        db.add_all([contract, batch])
        db.flush()
        item = AuditBatchItem(
            batch_id=batch.id,
            contract_id=contract.id,
            filename=contract.filename,
            status="auditing",
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        db.add(item)
        db.commit()
        contract_id, item_id = contract.id, item.id

    monkeypatch.setattr(audit_tasks, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(
        audit_tasks,
        "run_audit",
        lambda *_args, **_kwargs: pytest.fail("有效租约存在时不得重复执行审查"),
    )

    result = run_contract_audit.run(contract_id, ["legal"], item_id)

    assert result == {"contract_id": contract_id, "status": "already_running"}


def test_audit_task_reclaims_an_expired_lease(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = _user(db)
        contract = Contract(
            filename="contract.txt",
            storage_path=str(tmp_path / "contract.txt"),
            department=user.department,
            uploaded_by=user.id,
        )
        batch = AuditBatch(owner_id=user.id, department=user.department, idempotency_key="expired-lease")
        db.add_all([contract, batch])
        db.flush()
        item = AuditBatchItem(
            batch_id=batch.id,
            contract_id=contract.id,
            filename=contract.filename,
            status="parsing",
            lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        db.add(item)
        db.commit()
        contract_id, item_id = contract.id, item.id

    calls: list[int] = []
    monkeypatch.setattr(audit_tasks, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(
        audit_tasks,
        "run_audit",
        lambda _db, saved_contract, dimensions=None: (
            calls.append(saved_contract.id) or {"risk_count": 0, "cross_checks": []}
        ),
    )

    result = run_contract_audit.run(contract_id, ["legal"], item_id)

    assert result["status"] == "done"
    assert calls == [contract_id]


def test_recovery_dispatches_queued_and_expired_items_only(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = _user(db)
        batch = AuditBatch(
            owner_id=user.id,
            department=user.department,
            idempotency_key="recovery-scan",
        )
        db.add(batch)
        db.flush()
        contracts = [
            Contract(
                filename=f"contract-{index}.txt",
                storage_path=str(tmp_path / f"contract-{index}.txt"),
                department=user.department,
                uploaded_by=user.id,
            )
            for index in range(4)
        ]
        db.add_all(contracts)
        db.flush()
        now = datetime.now(timezone.utc)
        items = [
            AuditBatchItem(batch_id=batch.id, contract_id=contracts[0].id, filename=contracts[0].filename),
            AuditBatchItem(
                batch_id=batch.id,
                contract_id=contracts[1].id,
                filename=contracts[1].filename,
                status="auditing",
                lease_expires_at=now - timedelta(seconds=1),
            ),
            AuditBatchItem(
                batch_id=batch.id,
                contract_id=contracts[2].id,
                filename=contracts[2].filename,
                status="auditing",
                lease_expires_at=now + timedelta(minutes=10),
            ),
            AuditBatchItem(
                batch_id=batch.id,
                contract_id=contracts[3].id,
                filename=contracts[3].filename,
                status="done",
            ),
        ]
        db.add_all(items)
        db.commit()
        expected_ids = {items[0].id, items[1].id}

    dispatched: list[int] = []

    def fake_dispatch(_contract_id: int, _dimensions: list[str], item_id: int):
        dispatched.append(item_id)
        return f"recovery-{item_id}"

    count = audit_tasks.recover_orphaned_batch_items(
        session_factory=lambda: Session(engine),
        dispatch=fake_dispatch,
    )

    assert count == 2
    assert set(dispatched) == expected_ids

    second_count = audit_tasks.recover_orphaned_batch_items(
        session_factory=lambda: Session(engine),
        dispatch=fake_dispatch,
    )

    assert second_count == 0
    assert set(dispatched) == expected_ids


def test_retry_reuses_persisted_dimensions_by_default(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'retry.db').as_posix()}")
    Base.metadata.create_all(engine)
    db = Session(engine)
    user = _user(db)
    contract = Contract(
        filename="contract.txt",
        storage_path=str(tmp_path / "contract.txt"),
        department=user.department,
        uploaded_by=user.id,
    )
    batch = AuditBatch(
        owner_id=user.id,
        department=user.department,
        idempotency_key="retry-dimensions",
        dimensions_json='["legal", "payment"]',
    )
    db.add_all([contract, batch])
    db.flush()
    item = AuditBatchItem(
        batch_id=batch.id,
        contract_id=contract.id,
        filename=contract.filename,
        status="failed",
    )
    db.add(item)
    db.commit()
    dispatched: list[list[str]] = []
    def assert_committed_before_dispatch(saved_item: AuditBatchItem, dimensions: list[str]) -> str:
        with Session(engine) as observer:
            assert observer.get(AuditBatchItem, saved_item.id).status == "queued"
        dispatched.append(dimensions)
        return "retry-task"

    monkeypatch.setattr(batches, "_dispatch_item", assert_committed_before_dispatch)

    batches.retry_batch(batch.id, dimensions=None, db=db, user=user)

    assert dispatched == [["legal", "payment"]]


def test_celery_schedules_periodic_orphan_recovery():
    schedule = celery_app.conf.beat_schedule["recover-orphaned-audit-items"]

    assert schedule["task"] == "audit.recover_orphans"
    assert schedule["schedule"] <= 60
