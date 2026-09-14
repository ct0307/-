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
from app.services.audit.progress import publish_progress


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
        status="audit_failed",
        batch_id=batch.id,
        job_id=item.id,
        error_code=saved.error_code,
        error_message="模型调用超时",
        retryable=True,
    )
    assert item_payload.error_code == "MODEL_TIMEOUT"
    assert audit_payload.job_id == item.id
    assert audit_payload.retryable is True


def test_batch_item_schema_falls_back_for_historical_progress_fields():
    payload = BatchItemOut.model_validate({
        "id": 1,
        "contract_id": 2,
        "filename": "historical.txt",
        "status": "validating",
        "attempts": 0,
    })

    assert payload.progress == 90
    assert payload.progress_stage == "persisting"


def test_audit_response_exposes_typed_quality_fields_without_shared_defaults():
    first = AuditResponse(
        contract_id=1,
        status="review_required",
        quality_reasons=["PARSE_QUALITY_LOW"],
        coverage={"planned": 2, "completed": 1},
    )
    second = AuditResponse(contract_id=2, status="done")

    first.cross_checks.append({
        "id": "CC1", "from_agent": "legal", "to_agent": "finance",
        "trigger": "付款", "action": "复核", "verdict": "conflict",
        "note": "不一致", "category": "付款",
    })
    assert first.coverage.planned == 2
    assert first.quality_reasons == ["PARSE_QUALITY_LOW"]
    assert second.cross_checks == []
    assert second.quality_reasons == []
    assert second.coverage is None


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

    assert first.status == "queued"
    assert first.job_id is not None
    assert first.batch_id is not None
    assert first.task_id == "task-001"
    assert repeated.job_id == first.job_id
    assert dispatched == [(contract.id, ["legal"], first.job_id)]
    db.close()
    engine.dispose()


def test_audit_endpoint_replays_failed_item_as_audit_failed(monkeypatch):
    from app.api.v1.endpoints import contracts

    db = _session()
    user = _user(db)
    contract = Contract(
        filename="failed-replay.pdf",
        storage_path="/private/failed-replay.pdf",
        contract_type="采购合同",
        department=user.department,
        uploaded_by=user.id,
        status="parsed",
    )
    db.add(contract)
    db.commit()
    monkeypatch.setattr(contracts, "dispatch_audit_item", lambda *_args: "task-001")
    request = AuditRequest(contract_type="采购合同", dimensions=["legal"])
    first = contracts.audit_contract_endpoint(
        contract.id,
        request,
        idempotency_key="failed-replay-001",
        db=db,
        user=user,
    )
    item = db.get(AuditBatchItem, first.job_id)
    item.status = "failed"
    item.error_code = "MODEL_TIMEOUT"
    item.error = "模型调用超时，请稍后重试"
    db.commit()

    replay = contracts.audit_contract_endpoint(
        contract.id,
        request,
        idempotency_key="failed-replay-001",
        db=db,
        user=user,
    )

    assert replay.status == "audit_failed"
    assert replay.requires_review is False
    assert replay.error_code == "MODEL_TIMEOUT"


def test_audit_endpoint_replay_uses_selected_item_quality_snapshot(monkeypatch):
    from app.api.v1.endpoints import contracts

    db = _session()
    user = _user(db)
    contract = Contract(
        filename="snapshot.pdf",
        storage_path="/private/snapshot.pdf",
        contract_type="采购合同",
        department=user.department,
        uploaded_by=user.id,
        status="parsed",
    )
    db.add(contract)
    db.commit()
    monkeypatch.setattr(contracts, "dispatch_audit_item", lambda *_args: "task-001")
    request = AuditRequest(contract_type="采购合同", dimensions=["legal"])
    first = contracts.audit_contract_endpoint(
        contract.id,
        request,
        idempotency_key="snapshot-replay-001",
        db=db,
        user=user,
    )
    item = db.get(AuditBatchItem, first.job_id)
    item.status = "done"
    item.result_json = json.dumps({
        "risk_count": 2,
        "requires_review": True,
        "ocr_confidence": 0.62,
        "review_reason": "旧任务不应显示该原因",
        "quality_reasons": ["EVIDENCE_UNRESOLVED"],
        "coverage": {"planned": 2, "completed": 2},
        "cross_checks": [{
            "id": "CC-SNAPSHOT",
            "from_agent": "legal",
            "to_agent": "finance",
            "trigger": "付款冲突",
            "action": "复核",
            "verdict": "confirmed",
            "note": "已消解",
            "category": "付款",
        }],
    }, ensure_ascii=False)
    contract.audit_generation += 1
    contract.status = "review_required"
    contract.requires_review = True
    contract.ocr_confidence = 0.19
    contract.review_reason = "新一代合同状态"
    db.commit()

    replay = contracts.audit_contract_endpoint(
        contract.id,
        request,
        idempotency_key="snapshot-replay-001",
        db=db,
        user=user,
    )

    assert replay.status == "done"
    assert replay.risk_count == 2
    assert replay.requires_review is False
    assert replay.review_reason is None
    assert replay.quality_reasons == ["EVIDENCE_UNRESOLVED"]
    assert replay.coverage.model_dump() == {"planned": 2, "completed": 2}
    assert [value.id for value in replay.cross_checks] == ["CC-SNAPSHOT"]
    assert replay.ocr_confidence == 0.62
    restored = contracts.get_contract_audit_status(
        contract.id, job_id=item.id, db=db, user=user
    )
    assert restored.model_dump() == replay.model_dump()


@pytest.mark.parametrize(
    "snapshot",
    [
        "not-json",
        "[]",
        json.dumps({
            "risk_count": {"bad": True},
            "quality_reasons": ["VALID", 3],
            "coverage": {"planned": True, "completed": 0},
            "ocr_confidence": float("nan"),
            "cross_checks": [{"id": "missing-required-fields"}],
            "review_reason": {"bad": True},
        }),
        json.dumps({"ocr_confidence": True}),
        json.dumps({"ocr_confidence": {"bad": True}}),
        json.dumps({"ocr_confidence": -0.1}),
        json.dumps({"ocr_confidence": 1.1}),
        json.dumps({"ocr_confidence": 10 ** 400}),
    ],
)
def test_audit_status_bad_snapshot_fails_closed(snapshot):
    from app.api.v1.endpoints import contracts

    db = _session()
    user = _user(db)
    contract = Contract(
        filename="bad-snapshot.pdf",
        storage_path="/private/bad-snapshot.pdf",
        department=user.department,
        uploaded_by=user.id,
        status="review_required",
        requires_review=True,
        ocr_confidence=0.91,
        review_reason="合同当前状态不得污染任务快照",
    )
    batch = AuditBatch(
        owner_id=user.id,
        department=user.department,
        idempotency_key=f"bad-snapshot-{abs(hash(snapshot))}",
    )
    db.add_all([contract, batch])
    db.flush()
    item = AuditBatchItem(
        batch_id=batch.id,
        contract_id=contract.id,
        filename=contract.filename,
        status="review_required",
        result_json=snapshot,
    )
    db.add(item)
    db.commit()

    response = contracts.get_contract_audit_status(
        contract.id, job_id=item.id, db=db, user=user
    )

    assert response.status == "review_required"
    assert response.risk_count is None
    assert response.requires_review is True
    assert response.review_reason is None
    assert response.quality_reasons == []
    assert response.coverage is None
    assert response.cross_checks == []
    assert response.ocr_confidence is None


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
                "requires_review": False,
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
        status="reviewing",
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
    assert result.requires_review is False
    assert result.ocr_confidence == 0.61
    assert result.review_reason is None
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
    assert latest.risk_count is None


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

    timeout = classify_task_error(
        LLMError("任意安全消息", code="MODEL_TIMEOUT", retryable=False)
    )
    unavailable = classify_task_error(LLMError("LLM 请求失败：DNS error"))
    stale = classify_task_error(StaleAuditRun("generation mismatch"))
    internal = classify_task_error(RuntimeError("C:/secret/internal traceback"))

    assert (timeout.code, timeout.retryable) == ("MODEL_TIMEOUT", False)
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


def _task_fixture(*, active=False):
    db = _session()
    user = _user(db)
    contract = Contract(
        filename="lock-order.pdf", storage_path="/private/lock-order.pdf",
        uploaded_by=user.id, department=user.department,
        status="reviewing", audit_generation=1,
    )
    batch = AuditBatch(
        owner_id=user.id, department=user.department, total=1,
        idempotency_key="lock-order-test", request_fingerprint="a" * 64,
    )
    db.add_all([contract, batch])
    db.flush()
    item = AuditBatchItem(
        batch_id=batch.id, contract_id=contract.id, filename=contract.filename,
        status="reviewing" if active else "queued", audit_generation=1,
        lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=30) if active else None,
        execution_token="original-token" if active else None,
    )
    db.add(item)
    db.commit()
    engine, contract_id, item_id = db.get_bind(), contract.id, item.id
    db.close()
    return engine, contract_id, item_id


def test_publish_progress_is_monotonic_and_fenced():
    engine, contract_id, item_id = _task_fixture(active=True)
    try:
        with Session(engine) as db:
            assert publish_progress(
                db,
                item_id=item_id,
                contract_id=contract_id,
                generation=1,
                execution_token="original-token",
                progress=40,
                stage="reviewing",
            )
            assert not publish_progress(
                db,
                item_id=item_id,
                contract_id=contract_id,
                generation=1,
                execution_token="original-token",
                progress=40,
                stage="reviewing",
            )
            assert publish_progress(
                db,
                item_id=item_id,
                contract_id=contract_id,
                generation=1,
                execution_token="original-token",
                progress=20,
                stage="verifying",
            )
            assert not publish_progress(
                db,
                item_id=item_id,
                contract_id=contract_id,
                generation=1,
                execution_token="stale-token",
                progress=80,
                stage="reviewing",
            )

        with Session(engine) as db:
            saved = db.get(AuditBatchItem, item_id)
            assert saved.progress == 40
            assert saved.progress_stage == "verifying"
    finally:
        engine.dispose()


def test_duplicate_task_locks_contract_before_item_without_changing_owner(monkeypatch):
    from sqlalchemy import event
    from app.tasks import audit_tasks

    engine, contract_id, item_id = _task_fixture(active=True)
    locks = []
    db = Session(engine)

    def capture_locks(state):
        if state.is_select and state.statement._for_update_arg is not None:
            locks.extend(description["entity"] for description in state.statement.column_descriptions)

    event.listen(db, "do_orm_execute", capture_locks)
    monkeypatch.setattr(audit_tasks, "SessionLocal", lambda: db)
    try:
        result = audit_tasks.run_contract_audit.run(contract_id, [], item_id)
        assert result["status"] == "already_running"
        assert locks[:2] == [Contract, AuditBatchItem]
        with Session(engine) as check:
            item = check.get(AuditBatchItem, item_id)
            assert item.status == "reviewing"
            assert item.execution_token == "original-token"
    finally:
        engine.dispose()


@pytest.mark.parametrize("sqlstate", ["40P01", "40001", "55P03"])
def test_database_contention_sqlstates_are_safe_and_retryable(sqlstate):
    from sqlalchemy.exc import DBAPIError
    from app.tasks.audit_tasks import classify_task_error

    original = Exception("secret database details")
    original.sqlstate = sqlstate
    failure = classify_task_error(DBAPIError("secret SQL", {"secret": "value"}, original))
    assert failure.code == "AUDIT_PERSISTENCE_UNAVAILABLE"
    assert failure.retryable is True
    assert "secret" not in failure.message


@pytest.mark.parametrize("message", ["database is locked", "deadlock detected", "no such table: missing"])
def test_database_contention_messages_do_not_retry_schema_errors(message):
    from sqlalchemy.exc import OperationalError
    from app.tasks.audit_tasks import classify_task_error

    failure = classify_task_error(OperationalError("query", {}, Exception(message)))
    assert failure.retryable is (message != "no such table: missing")


def test_sql_parameters_cannot_turn_permanent_database_errors_into_retries():
    from sqlalchemy.exc import OperationalError
    from app.tasks.audit_tasks import classify_task_error

    error = OperationalError(
        "query", {"contract_text": "deadlock detected"}, Exception("no such table: missing")
    )
    assert classify_task_error(error).retryable is False


@pytest.mark.parametrize("retries", [0, 3])
def test_database_failure_before_claim_retries_without_publishing_failure(monkeypatch, retries):
    from celery.exceptions import Retry
    from sqlalchemy.exc import OperationalError
    from app.tasks import audit_tasks

    engine, contract_id, item_id = _task_fixture()
    db = Session(engine)
    real_query = db.query
    calls = 0

    def fail_first_query(*entities):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OperationalError("query", {}, Exception("deadlock detected"))
        return real_query(*entities)

    retry_calls = []

    def retry(**kwargs):
        retry_calls.append(kwargs)
        raise Retry("retry database contention")

    monkeypatch.setattr(db, "query", fail_first_query)
    monkeypatch.setattr(audit_tasks, "SessionLocal", lambda: db)
    monkeypatch.setattr(audit_tasks.run_contract_audit, "retry", retry)
    audit_tasks.run_contract_audit.push_request(retries=retries)
    try:
        expected = Retry if retries == 0 else OperationalError
        with pytest.raises(expected):
            audit_tasks.run_contract_audit.run(contract_id, [], item_id)
        assert len(retry_calls) == (1 if retries == 0 else 0)
        with Session(engine) as check:
            assert check.get(AuditBatchItem, item_id).status == "queued"
            assert check.get(Contract, contract_id).status == "reviewing"
    finally:
        audit_tasks.run_contract_audit.pop_request()
        engine.dispose()


def test_database_failure_after_claim_requeues_owned_item(monkeypatch):
    from celery.exceptions import Retry
    from sqlalchemy.exc import OperationalError
    from app.tasks import audit_tasks

    engine, contract_id, item_id = _task_fixture()

    def fail_audit(*args, **kwargs):
        raise OperationalError("query", {}, Exception("deadlock detected"))

    def retry(**kwargs):
        raise Retry("retry database contention")

    monkeypatch.setattr(audit_tasks, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(audit_tasks, "run_audit", fail_audit)
    monkeypatch.setattr(audit_tasks.run_contract_audit, "retry", retry)
    audit_tasks.run_contract_audit.push_request(retries=0)
    try:
        with pytest.raises(Retry):
            audit_tasks.run_contract_audit.run(contract_id, [], item_id)
        with Session(engine) as check:
            item = check.get(AuditBatchItem, item_id)
            assert item.status == "queued"
            assert item.attempts == 1
            assert item.execution_token is None
            assert item.lease_expires_at is None
            assert item.error_code == "AUDIT_PERSISTENCE_UNAVAILABLE"
            assert check.get(Contract, contract_id).status != "audit_failed"
    finally:
        audit_tasks.run_contract_audit.pop_request()
        engine.dispose()


@pytest.mark.parametrize("operation", ["flush", "commit"])
def test_database_failure_during_claim_retries_without_publishing_failure(monkeypatch, operation):
    from celery.exceptions import Retry
    from sqlalchemy.exc import OperationalError
    from app.tasks import audit_tasks

    engine, contract_id, item_id = _task_fixture()
    db = Session(engine)
    original = getattr(db, operation)
    failed = False

    def fail_claim(*args, **kwargs):
        nonlocal failed
        changing_item = any(isinstance(value, AuditBatchItem) for value in db.dirty)
        if not failed and (operation == "commit" or changing_item):
            failed = True
            raise OperationalError("query", {}, Exception("deadlock detected"))
        return original(*args, **kwargs)

    def retry(**kwargs):
        raise Retry("retry database contention")

    monkeypatch.setattr(db, operation, fail_claim)
    monkeypatch.setattr(audit_tasks, "SessionLocal", lambda: db)
    monkeypatch.setattr(audit_tasks.run_contract_audit, "retry", retry)
    audit_tasks.run_contract_audit.push_request(retries=0)
    try:
        with pytest.raises(Retry):
            audit_tasks.run_contract_audit.run(contract_id, [], item_id)
        assert failed is True
        with Session(engine) as check:
            item = check.get(AuditBatchItem, item_id)
            assert item.status == "queued"
            assert item.execution_token is None
            assert item.attempts == 0
    finally:
        audit_tasks.run_contract_audit.pop_request()
        engine.dispose()


@pytest.mark.parametrize("failures", [1, 4])
def test_local_dispatcher_uses_real_celery_retry_without_broker(monkeypatch, failures):
    from sqlalchemy.exc import OperationalError
    from app.tasks import audit_tasks, dispatcher

    engine, contract_id, item_id = _task_fixture(active=True)
    attempts = []
    initial_request = audit_tasks.run_contract_audit.request

    def session_factory():
        db = Session(engine)
        query = db.query
        attempts.append(audit_tasks.run_contract_audit.request.retries)

        def query_with_failure(*entities):
            if len(attempts) <= failures:
                raise OperationalError("query", {}, Exception("database is locked"))
            return query(*entities)

        db.query = query_with_failure
        return db

    def reject_broker(*args, **kwargs):
        pytest.fail("本地重试不应向消息队列投递任务")

    monkeypatch.setattr(audit_tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(audit_tasks.run_contract_audit, "apply_async", reject_broker)
    monkeypatch.setattr(dispatcher, "_sleep", lambda _seconds: None)
    try:
        if failures == 4:
            with pytest.raises(OperationalError):
                dispatcher._run_local(contract_id, [], item_id)
        else:
            dispatcher._run_local(contract_id, [], item_id)
        assert attempts == list(range(min(failures + 1, 4)))
        assert audit_tasks.run_contract_audit.request is initial_request
        with Session(engine) as check:
            assert check.get(AuditBatchItem, item_id).execution_token == "original-token"
    finally:
        engine.dispose()
