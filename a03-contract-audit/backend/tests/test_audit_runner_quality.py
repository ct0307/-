import pytest
from types import SimpleNamespace
from sqlalchemy import create_engine
from sqlalchemy.orm import Query, Session

from app.db.session import Base
from app.llm.base import LLMError
from app.models.models import AuditBatch, AuditBatchItem, Contract, Risk, User
from app.services.audit import runner
from app.services.audit.auditor import _record_llm_call
from app.services.audit.runner import run_audit
from app.services.parser.extractor import DocumentParseResult


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _contract(db: Session, name: str) -> Contract:
    contract = Contract(
        filename=name,
        storage_path=f"/{name}",
        department="法务部",
        uploaded_by=1,
    )
    db.add(contract)
    db.commit()
    db.refresh(contract)
    return contract


def test_low_confidence_ocr_requires_review_and_keeps_one_quality_risk(
    monkeypatch, db: Session
):
    contract = _contract(db, "scan.pdf")
    parsed = DocumentParseResult(
        text="有效合同正文" * 60,
        source="ocr",
        ocr_confidence=0.42,
        requires_review=True,
        review_reason="OCR 平均置信度低于 75%",
    )
    monkeypatch.setattr(runner, "extract_document", lambda _path: parsed)
    monkeypatch.setattr(
        runner,
        "audit_contract",
        lambda *_args, **_kwargs: {"risks": [], "cross_checks": []},
    )

    result = run_audit(db, contract)
    run_audit(db, contract)
    db.refresh(contract)
    risks = db.query(Risk).filter(Risk.contract_id == contract.id).all()

    assert contract.status == "review_required"
    assert contract.parse_source == "ocr"
    assert contract.ocr_confidence == 0.42
    assert contract.requires_review is True
    assert result["requires_review"] is True
    assert [risk.category for risk in risks].count("扫描件识别质量不足") == 1
    assert next(risk for risk in risks if risk.category == "扫描件识别质量不足").tier == "red"


def test_native_high_quality_contract_finishes_without_quality_risk(
    monkeypatch, db: Session
):
    contract = _contract(db, "native.txt")
    parsed = DocumentParseResult(text="有效合同正文" * 60, source="native")
    monkeypatch.setattr(runner, "extract_document", lambda _path: parsed)
    monkeypatch.setattr(
        runner,
        "audit_contract",
        lambda *_args, **_kwargs: {"risks": [], "cross_checks": []},
    )

    result = run_audit(db, contract)
    db.refresh(contract)

    assert contract.status == "done"
    assert contract.requires_review is False
    assert result["requires_review"] is False
    assert db.query(Risk).filter(Risk.contract_id == contract.id).count() == 0


def test_short_native_text_requires_review_without_duplicate_parse_risk(
    monkeypatch, db: Session
):
    contract = _contract(db, "short.txt")
    parsed = DocumentParseResult(text="内容残缺", source="native")
    monkeypatch.setattr(runner, "extract_document", lambda _path: parsed)
    monkeypatch.setattr(
        runner,
        "audit_contract",
        lambda *_args, **_kwargs: pytest.fail("短文本不应进入自动审查"),
    )

    result = run_audit(db, contract)
    run_audit(db, contract)
    db.refresh(contract)
    risks = db.query(Risk).filter(Risk.contract_id == contract.id).all()

    assert contract.requires_review is True
    assert contract.review_reason == "合同文本长度不足 200 字"
    assert contract.status == "review_required"
    assert result["requires_review"] is True
    assert [risk.category for risk in risks].count("文本解析失败") == 1


def test_run_audit_releases_claim_transaction_before_external_work(monkeypatch, db: Session):
    contract = _contract(db, "atomic.txt")
    parsed = DocumentParseResult(text="有效合同正文" * 60, source="native")
    transaction_states: list[bool] = []

    def fake_extract(_path):
        transaction_states.append(db.in_transaction())
        return parsed

    def fake_audit(*_args, **_kwargs):
        transaction_states.append(db.in_transaction())
        return {"risks": [], "cross_checks": []}

    monkeypatch.setattr(runner, "extract_document", fake_extract)
    monkeypatch.setattr(
        runner,
        "audit_contract",
        fake_audit,
    )

    lock_calls = 0
    original_with_for_update = Query.with_for_update

    def track_with_for_update(query, *args, **kwargs):
        nonlocal lock_calls
        lock_calls += 1
        return original_with_for_update(query, *args, **kwargs)

    commits = 0
    original_commit = db.commit

    def track_commit():
        nonlocal commits
        commits += 1
        return original_commit()

    monkeypatch.setattr(Query, "with_for_update", track_with_for_update)
    monkeypatch.setattr(db, "commit", track_commit)

    run_audit(db, contract)

    assert transaction_states == [False, False]
    assert lock_calls == 2
    assert commits == 2


def test_stale_audit_generation_cannot_publish(monkeypatch, db: Session):
    from app.services.audit.runner import StaleAuditRun

    contract = _contract(db, "stale.txt")
    old_risk = Risk(
        contract_id=contract.id,
        agent="legal",
        level="low",
        category="原结果",
        original_text="原文",
        basis="依据",
        suggestion="建议",
        confidence=80,
        tier="green",
        review_status="pending",
        rag_sources="[]",
    )
    db.add(old_risk)
    db.commit()
    parsed = DocumentParseResult(text="有效合同正文" * 60, source="native")
    monkeypatch.setattr(runner, "extract_document", lambda _path: parsed)

    def supersede_run(*_args, **_kwargs):
        current = db.get(Contract, contract.id)
        current.audit_generation += 1
        db.commit()
        return {"risks": [], "cross_checks": []}

    monkeypatch.setattr(runner, "audit_contract", supersede_run)

    with pytest.raises(StaleAuditRun):
        run_audit(db, contract)

    assert db.query(Risk).filter(Risk.contract_id == contract.id).count() == 1


def test_run_audit_restores_previous_status_after_failure(monkeypatch, db: Session):
    contract = _contract(db, "broken.pdf")
    contract.status = "parsed"
    db.commit()
    monkeypatch.setattr(
        runner,
        "extract_document",
        lambda _path: (_ for _ in ()).throw(RuntimeError("parse failed")),
    )

    with pytest.raises(RuntimeError, match="parse failed"):
        run_audit(db, contract)

    db.refresh(contract)
    assert contract.status == "parsed"


def test_run_audit_logs_structured_stage_timings_without_contract_text(monkeypatch, db: Session):
    contract = _contract(db, "timing.txt")
    sensitive_text = "SECRET-CONTRACT-BODY" * 20
    parsed = DocumentParseResult(text=sensitive_text, source="native")
    events: list[tuple[str, dict]] = []

    monkeypatch.setattr(runner, "extract_document", lambda _path: parsed)
    monkeypatch.setattr(
        runner,
        "audit_contract",
        lambda *_args, **_kwargs: {
            "risks": [],
            "cross_checks": [],
            "timings": {
                "legal_agent_ms": 11,
                "finance_agent_ms": 13,
                "grounding_ms": 7,
            },
        },
    )
    monkeypatch.setattr(
        runner.log,
        "info",
        lambda event, **fields: events.append((event, fields)),
    )

    run_audit(db, contract)

    fields = next(fields for event, fields in events if event == "audit.performance")
    assert fields["contract_id"] == contract.id
    assert fields["legal_agent_ms"] == 11
    assert fields["finance_agent_ms"] == 13
    assert fields["grounding_ms"] == 7
    assert all(fields[name] >= 0 for name in ("parse_ms", "persist_ms", "total_ms"))
    assert sensitive_text not in repr(fields)


def test_llm_call_log_joins_caller_transaction_without_committing():
    class FakeSession:
        def __init__(self):
            self.flushed = False
            self.committed = False

        def add(self, _row):
            pass

        def commit(self):
            self.committed = True

        def rollback(self):
            pass

        def close(self):
            pass

    db = FakeSession()
    response = SimpleNamespace(
        model="test-model",
        prompt_tokens=10,
        completion_tokens=5,
        latency_ms=20,
    )

    _record_llm_call(1, "legal", response, session_factory=lambda: db)

    assert db.committed is True


def test_llm_error_propagates_without_creating_a_fake_risk(monkeypatch):
    from app.services.audit import auditor

    monkeypatch.setattr(
        auditor,
        "_agent_audit",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            LLMError("C:/secret/provider timeout")
        ),
    )

    with pytest.raises(LLMError, match="provider timeout"):
        auditor.audit_contract({}, "有效合同正文" * 60)


def test_task_publish_rolls_back_risks_and_terminal_state_together(monkeypatch, db: Session):
    user = User(
        username="atomic-user",
        password_hash="not-used",
        role="legal",
        department="法务部",
    )
    db.add(user)
    db.flush()
    contract = Contract(
        filename="atomic-task.txt",
        storage_path="/atomic-task.txt",
        department=user.department,
        uploaded_by=user.id,
        status="auditing",
        audit_generation=1,
    )
    batch = AuditBatch(
        owner_id=user.id,
        department=user.department,
        idempotency_key="atomic-task-publish",
    )
    db.add_all([contract, batch])
    db.flush()
    item = AuditBatchItem(
        batch_id=batch.id,
        contract_id=contract.id,
        filename=contract.filename,
        status="auditing",
        audit_generation=1,
        execution_token="atomic-token",
    )
    db.add(item)
    db.commit()

    parsed = DocumentParseResult(text="有效合同正文" * 60, source="native")
    monkeypatch.setattr(runner, "extract_document", lambda _path: parsed)
    monkeypatch.setattr(
        runner,
        "audit_contract",
        lambda *_args, **_kwargs: {
            "risks": [{
                "agent": "legal",
                "level": "high",
                "category": "原子发布测试",
                "original_text": "测试原文",
                "basis": "测试依据",
                "suggestion": "测试建议",
                "confidence": 90,
                "tier": "red",
            }],
            "cross_checks": [],
        },
    )
    original_commit = db.commit
    commits = 0

    def fail_publish_commit():
        nonlocal commits
        commits += 1
        if commits == 1:
            raise RuntimeError("publish commit failed")
        return original_commit()

    monkeypatch.setattr(db, "commit", fail_publish_commit)

    with pytest.raises(RuntimeError, match="publish commit failed"):
        run_audit(
            db,
            contract,
            generation=1,
            batch_item_id=item.id,
            execution_token="atomic-token",
        )

    db.rollback()
    assert db.query(Risk).filter(Risk.contract_id == contract.id).count() == 0
    assert db.get(AuditBatchItem, item.id).status == "auditing"


def test_expired_worker_execution_token_cannot_publish(monkeypatch, db: Session):
    user = User(
        username="fencing-user",
        password_hash="not-used",
        role="legal",
        department="法务部",
    )
    db.add(user)
    db.flush()
    contract = Contract(
        filename="fencing.txt",
        storage_path="/fencing.txt",
        department=user.department,
        uploaded_by=user.id,
        status="auditing",
        audit_generation=1,
    )
    batch = AuditBatch(
        owner_id=user.id,
        department=user.department,
        idempotency_key="fencing-token-test",
    )
    db.add_all([contract, batch])
    db.flush()
    item = AuditBatchItem(
        batch_id=batch.id,
        contract_id=contract.id,
        filename=contract.filename,
        status="auditing",
        audit_generation=1,
        execution_token="new-worker-token",
    )
    db.add(item)
    db.commit()
    monkeypatch.setattr(
        runner,
        "extract_document",
        lambda _path: DocumentParseResult(text="有效合同正文" * 60, source="native"),
    )
    monkeypatch.setattr(
        runner,
        "audit_contract",
        lambda *_args, **_kwargs: {"risks": [], "cross_checks": []},
    )

    with pytest.raises(runner.StaleAuditRun, match="execution token"):
        run_audit(
            db,
            contract,
            generation=1,
            batch_item_id=item.id,
            execution_token="expired-worker-token",
        )

    assert db.get(AuditBatchItem, item.id).status == "auditing"
