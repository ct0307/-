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


def test_create_batch_keeps_committed_files_when_refresh_fails(monkeypatch, tmp_path):
    db = _session()
    user = _user(db)
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(
        db,
        "refresh",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("connection lost after commit")
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        batches.create_batch(
            files=_files(1),
            idempotency_key="batch-refresh-failure",
            contract_type="采购合同",
            dimensions=["legal"],
            db=db,
            user=user,
        )

    assert exc_info.value.status_code == 500
    assert db.query(Contract).count() == 1
    assert len(list(tmp_path.iterdir())) == 1


def test_create_batch_rejects_empty_contract_type_before_writing_files(monkeypatch, tmp_path):
    db = _session()
    user = _user(db)
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))

    with pytest.raises(HTTPException) as exc_info:
        batches.create_batch(_files(1), "missing-type", " ", [], db, user)

    assert exc_info.value.status_code == 422
    assert db.query(Contract).count() == 0
    assert list(tmp_path.iterdir()) == []


def test_create_batch_persists_dimensions_for_recovery(monkeypatch, tmp_path):
    db = _session()
    user = _user(db)
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(batches, "_dispatch_item", lambda _item, _dimensions: "task-1")

    result = batches.create_batch(
        _files(1), "recoverable", "采购合同", ["legal", "payment"], db, user
    )
    saved = db.get(AuditBatch, result.id)

    assert saved is not None
    assert json.loads(saved.dimensions_json) == ["legal", "payment"]


def test_create_batch_keeps_dispatch_failure_recoverable_and_safe(monkeypatch, tmp_path):
    db = _session()
    user = _user(db)
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(
        batches,
        "_dispatch_item",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("redis://worker:secret@queue.internal/0")
        ),
    )

    result = batches.create_batch(
        _files(1), "dispatch-pending", "采购合同", ["legal"], db, user
    )
    saved = db.get(AuditBatchItem, result.items[0].id)

    assert saved is not None
    assert saved.status == "queued"
    assert saved.task_id is None
    assert saved.error_code == "DISPATCH_PENDING"
    assert saved.error == "任务已保存，正在等待重新派发"
    assert "secret" not in repr(result.model_dump())


def test_completed_batch_item_uses_its_snapshot_instead_of_newer_contract_quality(tmp_path):
    db = _session()
    user = _user(db)
    contract = Contract(
        filename="scan.pdf",
        storage_path=str(tmp_path / "scan.pdf"),
        department=user.department,
        uploaded_by=user.id,
        requires_review=False,
        ocr_confidence=0.99,
        review_reason="新一代合同状态",
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
            status="review_required",
            result_json=json.dumps({
                "requires_review": True,
                "ocr_confidence": 0.42,
                "review_reason": "旧任务 OCR 平均置信度低于 75%",
            }, ensure_ascii=False),
        )
    )
    db.commit()

    payload = BatchOut.model_validate(batch).model_dump()
    item = payload["items"][0]

    assert item["status"] == "review_required"
    assert item["requires_review"] is True
    assert item["ocr_confidence"] == 0.42
    assert item["review_reason"] == "旧任务 OCR 平均置信度低于 75%"


def test_terminal_batch_item_defensively_ignores_corrupt_quality_snapshot(tmp_path):
    db = _session()
    user = _user(db)
    contract = Contract(
        filename="scan.pdf",
        storage_path=str(tmp_path / "scan.pdf"),
        department=user.department,
        uploaded_by=user.id,
        requires_review=True,
        ocr_confidence=0.45,
        review_reason="当前合同属于更新代次",
    )
    batch = AuditBatch(
        owner_id=user.id,
        department=user.department,
        idempotency_key="corrupt-quality-snapshot",
        status="done",
        total=1,
        completed=1,
    )
    db.add_all([contract, batch])
    db.flush()
    batch.items.append(AuditBatchItem(
        contract_id=contract.id,
        filename=contract.filename,
        status="done",
        result_json=json.dumps({
            "requires_review": "yes",
            "ocr_confidence": {"secret": "bad"},
            "review_reason": ["bad"],
        }),
    ))
    db.commit()

    item = BatchOut.model_validate(batch).model_dump()["items"][0]

    assert item["requires_review"] is False
    assert item["ocr_confidence"] is None
    assert item["review_reason"] is None


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

    first = batches.create_batch(files, "same-request", "采购合同", [], db, user)
    second = batches.create_batch(files, "same-request", "采购合同", [], db, user)

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


def test_get_batch_returns_authoritative_item_and_batch_progress():
    db = _session()
    user = _user(db)
    contracts = [
        Contract(
            filename=f"progress-{index}.txt",
            storage_path=f"/progress-{index}.txt",
            department=user.department,
            uploaded_by=user.id,
        )
        for index in range(2)
    ]
    batch = AuditBatch(
        owner_id=user.id,
        department=user.department,
        idempotency_key="batch-progress",
    )
    db.add_all([*contracts, batch])
    db.flush()
    batch.items.extend([
        AuditBatchItem(
            contract_id=contracts[0].id,
            filename=contracts[0].filename,
            status="reviewing",
            progress=50,
            progress_stage="reviewing",
        ),
        AuditBatchItem(
            contract_id=contracts[1].id,
            filename=contracts[1].filename,
            status="failed",
            progress=35,
            progress_stage="failed",
        ),
    ])
    db.commit()

    response = batches.get_batch(batch.id, db=db, user=user)

    assert response.progress == 75
    assert response.completed == 1
    assert response.failed == 1
    assert response.items[0].progress == 50
    assert response.items[0].progress_stage == "reviewing"
    assert response.items[1].progress == 35
    assert response.items[1].progress_stage == "failed"


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
        batches.create_batch(_files(2), "rollback", "采购合同", [], db, user)

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

    captured: list[tuple[list[str], float | None]] = []

    def fake_run_audit(
        _db,
        _contract,
        dimensions=None,
        *,
        generation=None,
        batch_item_id=None,
        execution_token=None,
        deadline=None,
        progress_callback=None,
    ):
        captured.append((dimensions or [], deadline))
        claimed_item = _db.get(AuditBatchItem, batch_item_id)
        assert claimed_item.progress == 5
        assert claimed_item.progress_stage == "claimed"
        assert progress_callback is not None
        progress_callback(40, "reviewing")
        cross_checks = [{
            "id": "CC1",
            "from": "legal",
            "to": "finance",
            "trigger": "付款冲突",
            "action": "复核",
            "verdict": "conflict",
            "note": "比例不一致",
            "category": "付款",
        }]
        saved_item = _db.get(AuditBatchItem, batch_item_id)
        saved_item.status = "done"
        saved_item.result_json = json.dumps({"risk_count": 1, "cross_checks": cross_checks})
        saved_item.finished_at = datetime.now(timezone.utc)
        _db.commit()
        return {
            "status": "done",
            "risk_count": 1,
            "cross_checks": cross_checks,
            "requires_review": False,
            "ocr_confidence": None,
            "review_reason": None,
        }

    monkeypatch.setattr(audit_tasks, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(audit_tasks, "run_audit", fake_run_audit)

    result = run_contract_audit.run(contract_id, ["legal"], item_id)
    repeated = run_contract_audit.run(contract_id, ["finance"], item_id)

    with Session(engine) as db:
        saved = db.get(AuditBatchItem, item_id)
        assert saved is not None
        assert saved.status == "done"
        assert saved.finished_at is not None
        assert saved.progress == 40
        assert saved.progress_stage == "reviewing"
        persisted_result = json.loads(saved.result_json)
        assert persisted_result["risk_count"] == 1
        assert persisted_result["cross_checks"][0]["id"] == "CC1"
    assert result["status"] == "done"
    assert repeated["status"] == "already_done"
    assert captured[0][0] == ["legal"]
    assert isinstance(captured[0][1], float)


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
        lambda _db, saved_contract, dimensions=None, **_kwargs: (
            calls.append(saved_contract.id)
            or {"status": "done", "risk_count": 0, "cross_checks": []}
        ),
    )

    result = run_contract_audit.run(contract_id, ["legal"], item_id)

    assert result["status"] == "done"
    assert calls == [contract_id]


def test_expired_worker_cannot_overwrite_new_execution_state(monkeypatch, tmp_path):
    from app.services.audit.runner import StaleAuditRun

    engine = create_engine(f"sqlite:///{(tmp_path / 'worker-fencing.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = _user(db)
        contract = Contract(
            filename="fencing.txt",
            storage_path=str(tmp_path / "fencing.txt"),
            department=user.department,
            uploaded_by=user.id,
            audit_generation=1,
        )
        batch = AuditBatch(
            owner_id=user.id,
            department=user.department,
            idempotency_key="worker-fencing",
        )
        db.add_all([contract, batch])
        db.flush()
        item = AuditBatchItem(
            batch_id=batch.id,
            contract_id=contract.id,
            filename=contract.filename,
            audit_generation=1,
        )
        db.add(item)
        db.commit()
        contract_id, item_id = contract.id, item.id

    def lose_lease(session, *_args, batch_item_id=None, **_kwargs):
        current = session.get(AuditBatchItem, batch_item_id)
        current.execution_token = "new-worker-token"
        current.status = "auditing"
        session.commit()
        raise StaleAuditRun("execution token mismatch")

    monkeypatch.setattr(audit_tasks, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(audit_tasks, "run_audit", lose_lease)

    with pytest.raises(StaleAuditRun):
        run_contract_audit.run(contract_id, ["legal"], item_id)

    with Session(engine) as db:
        saved = db.get(AuditBatchItem, item_id)
        assert saved.status == "auditing"
        assert saved.execution_token == "new-worker-token"
        assert saved.error_code is None
        assert saved.error is None


def test_old_generation_failure_cannot_overwrite_new_generation(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'generation-fencing.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = _user(db)
        contract = Contract(
            filename="generation.txt",
            storage_path=str(tmp_path / "generation.txt"),
            department=user.department,
            uploaded_by=user.id,
            status="reviewing",
            audit_generation=1,
        )
        batch = AuditBatch(
            owner_id=user.id,
            department=user.department,
            idempotency_key="generation-fencing",
        )
        db.add_all([contract, batch])
        db.flush()
        item = AuditBatchItem(
            batch_id=batch.id,
            contract_id=contract.id,
            filename=contract.filename,
            audit_generation=1,
        )
        db.add(item)
        db.commit()
        contract_id, item_id = contract.id, item.id

    def supersede_generation(session, *_args, batch_item_id=None, **_kwargs):
        current_contract = session.get(Contract, contract_id)
        current_item = session.get(AuditBatchItem, batch_item_id)
        current_contract.audit_generation = 2
        current_contract.status = "validating"
        current_item.audit_generation = 2
        current_item.status = "validating"
        session.commit()
        raise RuntimeError("old worker failed")

    monkeypatch.setattr(audit_tasks, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(audit_tasks, "run_audit", supersede_generation)

    with pytest.raises(RuntimeError, match="old worker failed"):
        run_contract_audit.run(contract_id, ["legal"], item_id)

    with Session(engine) as db:
        saved_contract = db.get(Contract, contract_id)
        saved_item = db.get(AuditBatchItem, item_id)
        assert saved_contract.audit_generation == 2
        assert saved_contract.status == "validating"
        assert saved_item.audit_generation == 2
        assert saved_item.status == "validating"
        assert saved_item.execution_token is not None
        assert saved_item.error_code is None


def test_stale_generation_worker_never_reopens_newer_completed_contract(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'stale-start.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as setup:
        user = _user(setup)
        contract = Contract(
            filename="stale.txt",
            storage_path=str(tmp_path / "stale.txt"),
            department=user.department,
            uploaded_by=user.id,
            status="reviewing",
            audit_generation=1,
        )
        batch = AuditBatch(
            owner_id=user.id,
            department=user.department,
            idempotency_key="stale-start",
        )
        setup.add_all([contract, batch])
        setup.flush()
        stale_item = AuditBatchItem(
            batch_id=batch.id,
            contract_id=contract.id,
            filename=contract.filename,
            status="queued",
            audit_generation=1,
        )
        setup.add(stale_item)
        setup.commit()
        contract_id, stale_item_id = contract.id, stale_item.id

    # 另一会话已完整发布更新代次，随后旧 worker 才真正启动。
    with Session(engine) as newer:
        current = newer.get(Contract, contract_id)
        current.audit_generation = 2
        current.status = "done"
        current.requires_review = False
        newer.commit()

    monkeypatch.setattr(audit_tasks, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(
        audit_tasks,
        "run_audit",
        lambda *_args, **_kwargs: pytest.fail("陈旧 worker 不得进入审查计算"),
    )

    result = run_contract_audit.run(contract_id, ["legal"], stale_item_id)

    assert result == {"contract_id": contract_id, "status": "stale"}
    with Session(engine) as verify:
        saved_contract = verify.get(Contract, contract_id)
        saved_item = verify.get(AuditBatchItem, stale_item_id)
        assert (saved_contract.audit_generation, saved_contract.status) == (2, "done")
        assert saved_item.status == "failed"
        assert saved_item.error_code == "STALE_AUDIT_RUN"
        assert saved_item.execution_token is None
        assert saved_item.lease_expires_at is None


def test_worker_failure_rechecks_token_inside_publish_transaction(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'failure-token-race.db').as_posix()}")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        user = _user(db)
        contract = Contract(
            filename="token-race.txt",
            storage_path=str(tmp_path / "token-race.txt"),
            department=user.department,
            uploaded_by=user.id,
            status="reviewing",
            audit_generation=1,
        )
        batch = AuditBatch(
            owner_id=user.id,
            department=user.department,
            idempotency_key="failure-token-race",
        )
        db.add_all([contract, batch])
        db.flush()
        item = AuditBatchItem(
            batch_id=batch.id,
            contract_id=contract.id,
            filename=contract.filename,
            audit_generation=1,
        )
        db.add(item)
        db.commit()
        contract_id, item_id = contract.id, item.id

    worker_sessions: list[Session] = []

    def session_factory():
        session = Session(engine)
        worker_sessions.append(session)
        return session

    class InterleavingFailure:
        code = "AUDIT_INTERNAL_ERROR"
        message = "审查任务执行失败，请联系管理员"

        @property
        def retryable(self):
            worker_sessions[0].rollback()
            with Session(engine) as replacement:
                current_contract = replacement.get(Contract, contract_id)
                current_item = replacement.get(AuditBatchItem, item_id)
                current_contract.status = "reviewing"
                current_item.status = "reviewing"
                current_item.execution_token = "new-worker-token"
                current_item.error_code = None
                current_item.error = None
                replacement.commit()
            return False

    def fail_after_claim(*_args, **_kwargs):
        raise RuntimeError("worker failed after claim")

    monkeypatch.setattr(audit_tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(audit_tasks, "classify_task_error", lambda _exc: InterleavingFailure())
    monkeypatch.setattr(audit_tasks, "run_audit", fail_after_claim)

    with pytest.raises(RuntimeError, match="worker failed after claim"):
        run_contract_audit.run(contract_id, ["legal"], item_id)

    with Session(engine) as db:
        saved_contract = db.get(Contract, contract_id)
        saved_item = db.get(AuditBatchItem, item_id)
        assert saved_contract.status == "reviewing"
        assert saved_item.status == "reviewing"
        assert saved_item.execution_token == "new-worker-token"
        assert saved_item.error_code is None
        assert saved_item.error is None


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


def test_recovery_redispatches_stale_queued_item_with_task_id(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'stale-queued.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = _user(db)
        contract = Contract(
            filename="stale.txt",
            storage_path=str(tmp_path / "stale.txt"),
            department=user.department,
            uploaded_by=user.id,
        )
        batch = AuditBatch(
            owner_id=user.id,
            department=user.department,
            idempotency_key="stale-queued-recovery",
        )
        db.add_all([contract, batch])
        db.flush()
        item = AuditBatchItem(
            batch_id=batch.id,
            contract_id=contract.id,
            filename=contract.filename,
            status="queued",
            task_id="lost-broker-message",
        )
        db.add(item)
        db.commit()
        db.execute(
            AuditBatchItem.__table__.update()
            .where(AuditBatchItem.id == item.id)
            .values(updated_at=datetime.now(timezone.utc) - timedelta(minutes=10))
        )
        db.commit()
        item_id = item.id

    dispatched: list[int] = []
    recovered = audit_tasks.recover_orphaned_batch_items(
        session_factory=lambda: Session(engine),
        dispatch=lambda _contract_id, _dimensions, saved_item_id: (
            dispatched.append(saved_item_id) or f"recovered-{saved_item_id}"
        ),
    )

    assert recovered == 1
    assert dispatched == [item_id]


def test_batch_dispatch_uses_shared_dispatcher(monkeypatch):
    calls: list[int] = []
    item = AuditBatchItem(id=7, contract_id=11, filename="contract.txt")
    monkeypatch.setattr(
        batches,
        "dispatch_audit_item",
        lambda saved_item, _dimensions: calls.append(saved_item.id) or "local:test",
    )

    assert batches._dispatch_item(item, ["legal"]) == "local:test"
    assert calls == [7]


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
        progress=68,
        progress_stage="failed",
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
    db.refresh(item)
    assert item.progress == 68
    assert item.progress_stage == "queued"


def test_celery_schedules_periodic_orphan_recovery():
    schedule = celery_app.conf.beat_schedule["recover-orphaned-audit-items"]

    assert schedule["task"] == "audit.recover_orphans"
    assert schedule["schedule"] <= 60
