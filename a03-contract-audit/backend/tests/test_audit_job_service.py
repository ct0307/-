"""单文件持久审查任务与上传幂等契约。"""
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.models import AuditBatch, AuditBatchItem, Contract, LLMCallLog, Risk, User
from app.schemas.batch import BatchItemOut
from app.schemas.contract import AuditResponse
from app.schemas.contract import AuditRequest


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _user(db: Session) -> User:
    user = User(
        username="legal-job-test",
        password_hash="not-used",
        role="legal",
        department="法务部",
    )
    db.add(user)
    db.flush()
    return user


def test_audit_reliability_fields_round_trip():
    db = _session()
    user = _user(db)
    contract = Contract(
        filename="contract.pdf",
        storage_path="/private/contract.pdf",
        department=user.department,
        uploaded_by=user.id,
        upload_idempotency_key="upload-request-001",
        content_sha256="a" * 64,
        audit_generation=2,
    )
    db.add(contract)
    db.flush()
    batch = AuditBatch(
        owner_id=user.id,
        department=user.department,
        idempotency_key="audit-request-001",
        request_fingerprint="b" * 64,
        total=1,
    )
    db.add(batch)
    db.flush()
    item = AuditBatchItem(
        batch_id=batch.id,
        contract_id=contract.id,
        filename=contract.filename,
        error_code="MODEL_TIMEOUT",
        result_json=json.dumps({"cross_checks": [{"id": "CC1"}]}),
    )
    db.add(item)
    db.flush()
    llm_log = LLMCallLog(
        contract_id=contract.id,
        audit_job_id=item.id,
        agent="legal",
        provider="test",
        model="test-model",
    )
    db.add(llm_log)
    db.commit()

    saved = db.get(AuditBatchItem, item.id)
    assert saved is not None
    assert saved.contract.audit_generation == 2
    assert saved.batch.request_fingerprint == "b" * 64
    assert saved.error_code == "MODEL_TIMEOUT"
    assert json.loads(saved.result_json)["cross_checks"][0]["id"] == "CC1"
    assert db.get(LLMCallLog, llm_log.id).audit_job_id == item.id

    item_payload = BatchItemOut.model_validate(saved)
    audit_payload = AuditResponse(
        contract_id=contract.id,
        status="failed",
        batch_id=batch.id,
        job_id=item.id,
        error_code=saved.error_code,
        error_message="模型调用超时",
        retryable=True,
    )
    assert item_payload.error_code == "MODEL_TIMEOUT"
    assert audit_payload.job_id == item.id
    assert audit_payload.retryable is True


def test_single_audit_job_is_idempotent_and_rejects_payload_mismatch():
    from app.services.audit.jobs import AuditJobConflict, create_single_audit_job

    db = _session()
    user = _user(db)
    contract = Contract(
        filename="contract.pdf",
        storage_path="/private/contract.pdf",
        contract_type="采购合同",
        department=user.department,
        uploaded_by=user.id,
        status="parsed",
    )
    db.add(contract)
    db.commit()

    first = create_single_audit_job(
        db,
        contract=contract,
        user=user,
        idempotency_key="audit-request-001",
        contract_type="采购合同",
        dimensions=["payment", "legal"],
    )
    repeated = create_single_audit_job(
        db,
        contract=contract,
        user=user,
        idempotency_key="audit-request-001",
        contract_type="采购合同",
        dimensions=["legal", "payment"],
    )

    assert first.created is True
    assert repeated.created is False
    assert repeated.batch.id == first.batch.id
    assert repeated.item.id == first.item.id
    assert db.query(AuditBatch).count() == 1
    assert db.query(AuditBatchItem).count() == 1
    assert first.item.status == "queued"
    assert first.item.audit_generation == 1
    assert contract.audit_generation == 1

    with pytest.raises(AuditJobConflict):
        create_single_audit_job(
            db,
            contract=contract,
            user=user,
            idempotency_key="audit-request-001",
            contract_type="采购合同",
            dimensions=["performance"],
        )


def test_audit_endpoint_commits_job_before_dispatch_and_dispatches_once(
    monkeypatch, tmp_path
):
    from app.api.v1.endpoints import contracts

    engine = create_engine(f"sqlite:///{(tmp_path / 'audit-endpoint.db').as_posix()}")
    Base.metadata.create_all(engine)
    db = Session(engine)
    user = _user(db)
    contract = Contract(
        filename="contract.pdf",
        storage_path="/private/contract.pdf",
        contract_type="采购合同",
        department=user.department,
        uploaded_by=user.id,
        status="parsed",
    )
    db.add(contract)
    db.commit()
    dispatched: list[tuple[int, list[str], int]] = []

    def fake_dispatch(item: AuditBatchItem, dimensions: list[str]) -> str:
        with Session(engine) as observer:
            persisted = observer.get(AuditBatchItem, item.id)
            assert persisted is not None
            assert persisted.status == "queued"
        dispatched.append((item.contract_id, dimensions, item.id))
        return "task-001"

    monkeypatch.setattr(contracts, "dispatch_audit_item", fake_dispatch, raising=False)
    monkeypatch.setattr(
        contracts,
        "run_audit",
        lambda *_args, **_kwargs: pytest.fail("审查端点不得同步调用模型"),
    )

    first = contracts.audit_contract_endpoint(
        contract.id,
        AuditRequest(contract_type="采购合同", dimensions=["legal"]),
        idempotency_key="audit-endpoint-001",
        db=db,
        user=user,
    )
    repeated = contracts.audit_contract_endpoint(
        contract.id,
        AuditRequest(contract_type="采购合同", dimensions=["legal"]),
        idempotency_key="audit-endpoint-001",
        db=db,
        user=user,
    )

    assert first.status == "auditing"
    assert first.job_id is not None
    assert first.batch_id is not None
    assert first.task_id == "task-001"
    assert repeated.job_id == first.job_id
    assert dispatched == [(contract.id, ["legal"], first.job_id)]
    db.close()
    engine.dispose()


def test_audit_status_restores_persisted_result_and_failure_details():
    from app.api.v1.endpoints import contracts

    db = _session()
    user = _user(db)
    contract = Contract(
        filename="contract.pdf",
        storage_path="/private/contract.pdf",
        contract_type="采购合同",
        department=user.department,
        uploaded_by=user.id,
        status="done",
        audit_generation=2,
    )
    batch = AuditBatch(
        owner_id=user.id,
        department=user.department,
        idempotency_key="audit-status-result",
        request_fingerprint="c" * 64,
        status="done",
        total=1,
        completed=1,
    )
    db.add_all([contract, batch])
    db.flush()
    item = AuditBatchItem(
        batch_id=batch.id,
        contract_id=contract.id,
        filename=contract.filename,
        status="done",
        task_id="task-done",
        audit_generation=1,
        result_json=json.dumps(
            {
                "risk_count": 3,
                "requires_review": True,
                "ocr_confidence": 0.61,
                "review_reason": "任务 A 的质量快照",
                "cross_checks": [
                    {
                        "id": "CC1",
                        "from_agent": "legal",
                        "to_agent": "finance",
                        "trigger": "付款冲突",
                        "action": "复核",
                        "verdict": "conflict",
                        "note": "比例不一致",
                        "category": "付款",
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )
    db.add(item)
    db.commit()

    newer_batch = AuditBatch(
        owner_id=user.id,
        department=user.department,
        idempotency_key="audit-status-newer",
        request_fingerprint="d" * 64,
    )
    db.add(newer_batch)
    db.flush()
    newer = AuditBatchItem(
        batch_id=newer_batch.id,
        contract_id=contract.id,
        filename=contract.filename,
        status="auditing",
        audit_generation=2,
    )
    db.add(newer)
    db.flush()
    db.add_all([
        Risk(
            contract_id=contract.id,
            audit_job_id=item.id,
            agent="legal",
            level="high",
            category="任务 A 风险",
            original_text="A",
            basis="A",
            suggestion="A",
            confidence=90,
            tier="red",
        ),
        Risk(
            contract_id=contract.id,
            audit_job_id=newer.id,
            agent="legal",
            level="low",
            category="任务 B 风险",
            original_text="B",
            basis="B",
            suggestion="B",
            confidence=90,
            tier="green",
        ),
    ])
    contract.requires_review = False
    contract.ocr_confidence = 0.99
    contract.review_reason = "任务 B 的当前状态"
    db.commit()

    result = contracts.get_contract_audit_status(
        contract.id, job_id=item.id, db=db, user=user
    )
    assert result.job_id == item.id
    assert result.batch_id == batch.id
    assert result.risk_count == 3
    assert [cross.id for cross in result.cross_checks] == ["CC1"]
    assert result.requires_review is True
    assert result.ocr_confidence == 0.61
    assert result.review_reason == "任务 A 的质量快照"
    risks = contracts.get_contract_risks(
        contract.id, job_id=item.id, db=db, user=user
    )
    assert [risk.category for risk in risks] == ["任务 A 风险"]

    item.status = "failed"
    item.error_code = "MODEL_TIMEOUT"
    item.error = "模型调用超时，请稍后重试"
    db.commit()

    failed = contracts.get_contract_audit_status(
        contract.id, job_id=item.id, db=db, user=user
    )
    assert failed.status == "audit_failed"
    assert failed.error_code == "MODEL_TIMEOUT"
    assert failed.error_message == "模型调用超时，请稍后重试"
    assert failed.retryable is True

    latest = contracts.get_contract_audit_status(contract.id, db=db, user=user)
    assert latest.job_id == newer.id
    assert latest.risk_count == 1


def test_audit_status_rejects_job_from_another_contract():
    from app.api.v1.endpoints import contracts

    db = _session()
    user = _user(db)
    first = Contract(
        filename="first.pdf",
        storage_path="/private/first.pdf",
        department=user.department,
        uploaded_by=user.id,
    )
    second = Contract(
        filename="second.pdf",
        storage_path="/private/second.pdf",
        department=user.department,
        uploaded_by=user.id,
    )
    batch = AuditBatch(
        owner_id=user.id,
        department=user.department,
        idempotency_key="cross-contract-status",
    )
    db.add_all([first, second, batch])
    db.flush()
    item = AuditBatchItem(
        batch_id=batch.id,
        contract_id=second.id,
        filename=second.filename,
    )
    db.add(item)
    db.commit()

    with pytest.raises(HTTPException) as exc_info:
        contracts.get_contract_audit_status(
            first.id, job_id=item.id, db=db, user=user
        )

    assert getattr(exc_info.value, "status_code", None) == 404


def test_newer_audit_request_claims_a_higher_generation():
    from app.services.audit.jobs import create_single_audit_job

    db = _session()
    user = _user(db)
    contract = Contract(
        filename="ordered.pdf",
        storage_path="/private/ordered.pdf",
        contract_type="采购合同",
        department=user.department,
        uploaded_by=user.id,
        status="parsed",
    )
    db.add(contract)
    db.commit()

    older = create_single_audit_job(
        db,
        contract=contract,
        user=user,
        idempotency_key="ordered-audit-older",
        contract_type="采购合同",
        dimensions=["legal"],
    )
    newer = create_single_audit_job(
        db,
        contract=contract,
        user=user,
        idempotency_key="ordered-audit-newer",
        contract_type="采购合同",
        dimensions=["legal"],
    )

    assert older.item.audit_generation == 1
    assert newer.item.audit_generation == 2
    assert contract.audit_generation == 2


def test_local_dispatcher_recovers_jobs_left_by_previous_process(tmp_path):
    from app.tasks.dispatcher import recover_local_audit_items

    engine = create_engine(f"sqlite:///{(tmp_path / 'local-recovery.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = _user(db)
        contract = Contract(
            filename="contract.pdf",
            storage_path="/private/contract.pdf",
            contract_type="采购合同",
            department=user.department,
            uploaded_by=user.id,
            status="auditing",
        )
        batch = AuditBatch(
            owner_id=user.id,
            department=user.department,
            idempotency_key="local-recovery",
            dimensions_json='["legal"]',
            total=1,
        )
        db.add_all([contract, batch])
        db.flush()
        item = AuditBatchItem(
            batch_id=batch.id,
            contract_id=contract.id,
            filename=contract.filename,
            status="auditing",
            task_id="local:old-process",
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=20),
        )
        db.add(item)
        db.commit()
        item_id = item.id

    dispatched: list[tuple[int, list[str], int]] = []

    def fake_dispatch(contract_id: int, dimensions: list[str], job_id: int) -> str:
        dispatched.append((contract_id, dimensions, job_id))
        return "local:new-process"

    recovered = recover_local_audit_items(
        session_factory=lambda: Session(engine),
        dispatch=fake_dispatch,
    )

    with Session(engine) as db:
        saved = db.get(AuditBatchItem, item_id)
        assert saved is not None
        assert saved.status == "queued"
        assert saved.task_id == "local:new-process"
        assert saved.lease_expires_at is None
    assert recovered == 1
    assert dispatched[0][2] == item_id
    engine.dispose()


def test_audit_task_errors_are_classified_for_safe_retry_policy():
    from app.llm.base import LLMError
    from app.services.audit.runner import StaleAuditRun
    from app.tasks.audit_tasks import classify_task_error

    timeout = classify_task_error(LLMError("LLM 调用超时（120s）"))
    unavailable = classify_task_error(LLMError("LLM 请求失败：DNS error"))
    stale = classify_task_error(StaleAuditRun("generation mismatch"))
    internal = classify_task_error(RuntimeError("C:/secret/internal traceback"))

    assert (timeout.code, timeout.retryable) == ("MODEL_TIMEOUT", True)
    assert (unavailable.code, unavailable.retryable) == ("MODEL_UNAVAILABLE", True)
    assert (stale.code, stale.retryable) == ("STALE_AUDIT_RUN", False)
    assert (internal.code, internal.retryable) == ("AUDIT_INTERNAL_ERROR", False)
    assert "secret" not in internal.message.lower()


def test_local_dispatcher_executes_celery_retry_signal(monkeypatch):
    from celery.exceptions import Retry
    from app.tasks import audit_tasks, dispatcher

    attempts = 0

    def fake_run(_contract_id, _dimensions, _item_id):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise Retry("retry locally")

    monkeypatch.setattr(audit_tasks.run_contract_audit, "run", fake_run)
    monkeypatch.setattr(dispatcher, "_sleep", lambda _seconds: None, raising=False)

    dispatcher._run_local(1, ["legal"], 9)

    assert attempts == 2
