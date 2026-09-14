import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Query, Session, sessionmaker

from app.db.session import Base
from app.llm.base import LLMError, LLMResponse
from app.models.models import AuditBatch, AuditBatchItem, Contract, ContractClause, Risk, User
from app.services.audit import runner
from app.services.audit.runner import run_audit
from app.services.parser.extractor import DocumentBlock, DocumentParseResult, SourceAnchor


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


def test_low_confidence_ocr_requires_review_without_publishing_quality_risk(
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
        lambda *_args, **_kwargs: {
            "risks": [], "cross_checks": [], "issues": [],
            "coverage": {"planned": 1, "completed": 1},
        },
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
    assert result["status"] == "review_required"
    assert result["quality_reasons"] == ["PARSE_QUALITY_LOW"]
    assert risks == []


def test_audit_does_not_overwrite_existing_element_review_with_clean_decision(
    monkeypatch, db: Session
):
    contract = _contract(db, "element-conflict.txt")
    contract.requires_review = True
    contract.review_reason = "关键要素冲突，请人工确认"
    contract.status = "review_required"
    db.commit()
    parsed = DocumentParseResult(text="有效合同正文" * 60, source="native")
    monkeypatch.setattr(runner, "extract_document", lambda _path: parsed)
    monkeypatch.setattr(
        runner,
        "audit_contract",
        lambda *_args, **_kwargs: {
            "risks": [], "cross_checks": [], "issues": [],
            "coverage": {"planned": 1, "completed": 1},
        },
    )

    result = run_audit(db, contract)
    db.refresh(contract)

    assert result["status"] == "review_required"
    assert result["requires_review"] is True
    assert contract.status == "review_required"
    assert contract.review_reason == "关键要素冲突，请人工确认"


def test_native_high_quality_contract_finishes_without_quality_risk(
    monkeypatch, db: Session
):
    contract = _contract(db, "native.txt")
    parsed = DocumentParseResult(text="有效合同正文" * 60, source="native")
    monkeypatch.setattr(runner, "extract_document", lambda _path: parsed)
    monkeypatch.setattr(
        runner,
        "audit_contract",
        lambda *_args, **_kwargs: {
            "risks": [], "cross_checks": [], "issues": [],
            "coverage": {"planned": 1, "completed": 1},
        },
    )

    result = run_audit(db, contract)
    db.refresh(contract)

    assert contract.status == "done"
    assert contract.requires_review is False
    assert result["requires_review"] is False
    assert result["status"] == "done"
    assert result["coverage"] == {"planned": 1, "completed": 1}
    assert db.query(Risk).filter(Risk.contract_id == contract.id).count() == 0


def test_run_audit_reports_parse_and_persists_terminal_progress(
    monkeypatch, db: Session
):
    contract = _contract(db, "progress.txt")
    contract.status = "reviewing"
    contract.audit_generation = 1
    batch = AuditBatch(
        owner_id=1,
        department=contract.department,
        idempotency_key="progress-runner",
    )
    db.add(batch)
    db.flush()
    item = AuditBatchItem(
        batch_id=batch.id,
        contract_id=contract.id,
        filename=contract.filename,
        status="reviewing",
        audit_generation=1,
        execution_token="progress-token",
    )
    db.add(item)
    db.commit()

    monkeypatch.setattr(
        runner,
        "extract_document",
        lambda _path: DocumentParseResult(
            text="有效合同正文" * 60,
            source="native",
        ),
    )

    def fake_audit(*_args, progress_callback=None, **_kwargs):
        assert progress_callback is not None
        progress_callback(45, "reviewing")
        progress_callback(90, "verifying")
        return {
            "risks": [],
            "cross_checks": [],
            "issues": [],
            "coverage": {"planned": 1, "completed": 1},
        }

    monkeypatch.setattr(runner, "audit_contract", fake_audit)
    events = []

    result = run_audit(
        db,
        contract,
        generation=1,
        batch_item_id=item.id,
        execution_token="progress-token",
        progress_callback=lambda value, stage: events.append((value, stage)),
    )

    db.expire_all()
    saved_item = db.get(AuditBatchItem, item.id)
    assert events == [
        (15, "parsing"),
        (45, "reviewing"),
        (90, "verifying"),
    ]
    assert result["status"] == "done"
    assert saved_item.progress == 100
    assert saved_item.progress_stage == "completed"


def test_cross_dimension_candidate_requires_review_instead_of_done(
    monkeypatch, db: Session
):
    from app.services.audit import auditor

    contract = _contract(db, "dimension-mismatch.txt")
    quote = "第一条 合同主体具备合法签约资格"
    parsed = DocumentParseResult(
        text=quote + "。双方应当遵守合同约定。" * 30,
        source="native",
    )
    source = {
        "content": "付款金额异常时，应当核验付款金额和合同价款。",
        "source": "测试付款规则",
        "reliable": True,
    }

    class Adapter:
        def chat(self, *_args, **_kwargs):
            return LLMResponse(
                text=json.dumps({
                    "risks": [{
                        "level": "medium",
                        "category": "付款金额异常",
                        "quote": quote,
                        "reason": "付款金额需要进一步核验",
                        "suggestion": "补充明确的付款金额",
                    }],
                    "has_more": False,
                }, ensure_ascii=False),
                model="test",
            )

    monkeypatch.setattr(runner, "extract_document", lambda _path: parsed)
    monkeypatch.setattr(auditor, "get_llm_adapter", lambda: Adapter())
    monkeypatch.setattr(auditor, "retrieve", lambda *_args, **_kwargs: [source])

    result = run_audit(db, contract, dimensions=["legal"])
    db.refresh(contract)

    assert contract.status == "review_required"
    assert result["status"] == "review_required"
    assert result["quality_reasons"] == ["DIMENSION_MISMATCH"]
    assert [issue["code"] for issue in result["issues"]] == [
        "DIMENSION_MISMATCH"
    ]
    assert db.query(Risk).filter(Risk.contract_id == contract.id).count() == 0


def test_nonexistent_amount_claim_requires_review_instead_of_done(
    monkeypatch, db: Session
):
    from app.services.audit import auditor

    contract = _contract(db, "fact-mismatch.txt")
    quote = "第一条 合同价款为人民币100元"
    parsed = DocumentParseResult(
        text=quote + "。付款金额以本条约定为准。" * 30,
        source="native",
    )
    source = {
        "content": "付款金额异常时，应当核验合同价款和付款金额。",
        "source": "测试付款规则",
        "reliable": True,
    }

    class Adapter:
        def chat(self, *_args, **_kwargs):
            return LLMResponse(
                text=json.dumps({
                    "risks": [{
                        "level": "medium",
                        "category": "付款金额异常",
                        "quote": quote,
                        "reason": "合同价款记载为人民币200元",
                        "suggestion": "核对并统一合同价款",
                    }],
                    "has_more": False,
                }, ensure_ascii=False),
                model="test",
            )

    monkeypatch.setattr(runner, "extract_document", lambda _path: parsed)
    monkeypatch.setattr(auditor, "get_llm_adapter", lambda: Adapter())
    monkeypatch.setattr(auditor, "retrieve", lambda *_args, **_kwargs: [source])

    result = run_audit(db, contract, dimensions=["payment"])
    db.refresh(contract)

    assert contract.status == "review_required"
    assert result["status"] == "review_required"
    assert result["quality_reasons"] == ["FACT_VALIDATION_FAILED"]
    assert [issue["code"] for issue in result["issues"]] == [
        "FACT_VALIDATION_FAILED"
    ]
    assert db.query(Risk).filter(Risk.contract_id == contract.id).count() == 1


@pytest.mark.parametrize(
    "coverage",
    [
        None,
        {"planned": True, "completed": True},
        {"planned": "1", "completed": "1"},
        {"planned": 1.0, "completed": 1.0},
    ],
    ids=["missing", "bool", "numeric-string", "float"],
)
def test_invalid_audit_coverage_fails_closed(monkeypatch, db: Session, coverage):
    contract = _contract(db, "invalid-coverage.txt")
    monkeypatch.setattr(
        runner,
        "extract_document",
        lambda _path: DocumentParseResult(text="有效合同正文" * 60, source="native"),
    )
    model_result = {"risks": [], "cross_checks": [], "issues": []}
    if coverage is not None:
        model_result["coverage"] = coverage
    monkeypatch.setattr(runner, "audit_contract", lambda *_args, **_kwargs: model_result)

    result = run_audit(db, contract)

    assert result["status"] == "audit_failed"
    assert result["coverage"] == {"planned": 0, "completed": 0}
    assert [issue["code"] for issue in result["issues"]] == ["INVALID_MODEL_OUTPUT"]


def test_run_audit_persists_clauses_claims_and_contract_evidence(monkeypatch, db: Session):
    contract = _contract(db, "traceable.pdf")
    first_clause = "第一条 项目内容为企业合同审查系统开发，并包括部署、培训和验收支持。" * 3
    second_clause = "第二条 甲方应在验收后十日内支付全部款项，并按约定提供验收确认文件。" * 3
    parsed = DocumentParseResult(
        text=f"{first_clause}\n{second_clause}",
        source="native",
        blocks=(
            DocumentBlock(
                block_id="pdf-page-1-line-1",
                block_type="page_text",
                text=first_clause,
                anchor=SourceAnchor(page_number=1, bbox=(10.0, 20.0, 500.0, 40.0)),
            ),
            DocumentBlock(
                block_id="pdf-page-2-line-1",
                block_type="page_text",
                text=second_clause,
                anchor=SourceAnchor(page_number=2, bbox=(10.0, 24.0, 510.0, 44.0)),
            ),
        ),
    )
    monkeypatch.setattr(runner, "extract_document", lambda _path: parsed)
    monkeypatch.setattr(
        runner,
        "audit_contract",
        lambda *_args, **_kwargs: {
            "risks": [{
                "claim_id": "C-PAYMENT-001",
                "claim_status": "accepted",
                "source_window_id": "window-payment",
                "source_clause_ids": ["第二条"],
                "evidence_ids": ["LAW-585"],
                "retrieval_attempts": [{
                    "attempt": 1,
                    "query": "付款期限",
                    "support_status": "supported",
                    "source_ids": ["LAW-585"],
                }],
                "agent": "legal",
                "level": "medium",
                "category": "付款期限风险",
                "original_text": "验收后十日内支付全部款项",
                "risk_reason": "付款条件需要核验",
                "basis": "民法典第五百八十五条",
                "suggestion": "明确验收文件送达时间",
                "confidence": 88,
                "tier": "green",
                "evidence_status": "supported",
                "original_text_verified": True,
                "requires_manual_review": False,
                "rag_sources": [],
                }],
                "cross_checks": [],
                "coverage": {"planned": 1, "completed": 1},
            },
        )

    run_audit(db, contract)

    clauses = (
        db.query(ContractClause)
        .filter(ContractClause.contract_id == contract.id)
        .order_by(ContractClause.char_start)
        .all()
    )
    risk = db.query(Risk).filter(Risk.contract_id == contract.id).one()

    assert [clause.clause_id for clause in clauses] == ["第一条", "第二条"]
    assert json.loads(clauses[1].source_anchors_json)[0]["page_number"] == 2
    assert risk.claim_id == "C-PAYMENT-001"
    assert risk.claim_status == "accepted"
    assert json.loads(risk.source_clause_ids_json) == ["第二条"]
    assert json.loads(risk.evidence_ids_json) == ["LAW-585"]
    assert json.loads(risk.retrieval_attempts_json)[0]["attempt"] == 1
    contract_evidence = json.loads(risk.contract_evidence_json)
    assert contract_evidence[0]["clause_id"] == "第二条"
    assert contract_evidence[0]["match_type"] == "exact_quote"
    assert contract_evidence[0]["anchors"][0]["page_number"] == 2


def test_evidence_gap_promotes_contract_to_manual_review(monkeypatch, db: Session):
    contract = _contract(db, "evidence-gap.txt")
    parsed = DocumentParseResult(text="有效合同正文" * 60, source="native")
    monkeypatch.setattr(runner, "extract_document", lambda _path: parsed)
    monkeypatch.setattr(
        runner,
        "audit_contract",
        lambda *_args, **_kwargs: {
            "risks": [{
                "agent": "legal",
                "level": "medium",
                "category": "待核验风险",
                "original_text": "候选原文",
                "risk_reason": "需要补充证据",
                "basis": "无可靠检索依据，请人工复核",
                "suggestion": "请法务复核",
                "confidence": 0,
                "tier": "yellow",
                "evidence_status": "unsupported",
                "original_text_verified": False,
                "requires_manual_review": True,
                "rag_sources": [],
                }],
                "cross_checks": [],
                "coverage": {"planned": 1, "completed": 1},
            },
        )

    result = run_audit(db, contract)
    db.refresh(contract)

    assert result["requires_review"] is True
    assert contract.requires_review is True
    assert contract.status == "review_required"
    assert contract.review_reason == "风险原文尚未核验；风险依据尚未核验"
    risk = db.query(Risk).filter(Risk.contract_id == contract.id).one()
    assert risk.support_validator_version == "unvalidated"


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
    assert contract.review_reason == "合同文本不完整，需人工复核"
    assert contract.status == "review_required"
    assert result["requires_review"] is True
    assert result["status"] == "review_required"
    assert result["quality_reasons"] == ["CONTRACT_TEXT_INCOMPLETE"]
    assert risks == []


def test_failed_quality_keeps_previous_pending_risks(monkeypatch, db: Session):
    contract = _contract(db, "failed-quality.txt")
    previous = Risk(
        contract_id=contract.id,
        agent="legal",
        level="low",
        category="上一代风险",
        original_text="上一代原文",
        basis="上一代依据",
        suggestion="上一代建议",
        confidence=80,
        tier="green",
        review_status="pending",
        rag_sources="[]",
    )
    db.add(previous)
    db.commit()
    monkeypatch.setattr(
        runner,
        "extract_document",
        lambda _path: DocumentParseResult(text="有效合同正文" * 60, source="native"),
    )
    monkeypatch.setattr(
        runner,
        "audit_contract",
        lambda *_args, **_kwargs: {
            "risks": [],
            "cross_checks": [],
            "issues": [{
                "code": "MODEL_TIMEOUT",
                "agent": "legal",
                "window_id": "legal-1",
                "detail": "模型超时",
            }],
            "coverage": {"planned": 1, "completed": 0},
        },
    )

    result = run_audit(db, contract)

    db.refresh(contract)
    assert result["status"] == "audit_failed"
    assert result["risk_count"] == 0
    assert contract.status == "audit_failed"
    assert contract.requires_review is False
    assert db.query(Risk).filter(Risk.contract_id == contract.id).one().id == previous.id


def test_partial_failure_publishes_verified_risk_and_quality_snapshot(monkeypatch, db: Session):
    user = User(
        username="partial-user",
        password_hash="not-used",
        role="legal",
        department="法务部",
    )
    db.add(user)
    db.flush()
    contract = Contract(
        filename="partial.txt",
        storage_path="/partial.txt",
        department=user.department,
        uploaded_by=user.id,
        status="reviewing",
        audit_generation=4,
    )
    batch = AuditBatch(
        owner_id=user.id,
        department=user.department,
        idempotency_key="partial-quality",
    )
    db.add_all([contract, batch])
    db.flush()
    item = AuditBatchItem(
        batch_id=batch.id,
        contract_id=contract.id,
        filename=contract.filename,
        status="reviewing",
        audit_generation=4,
        execution_token="partial-token",
    )
    db.add(item)
    db.commit()
    observed_generations: list[int] = []
    monkeypatch.setattr(
        runner,
        "extract_document",
        lambda _path: DocumentParseResult(text="有效合同正文" * 60, source="native"),
    )

    def fake_audit(*_args, audit_generation=0, **_kwargs):
        observed_generations.append(audit_generation)
        return {
            "risks": [{
                "agent": "legal",
                "level": "medium",
                "category": "已核验风险",
                "original_text": "有效合同正文",
                "risk_reason": "存在付款风险",
                "basis": "已核验依据",
                "suggestion": "补充付款条件",
                "confidence": 88,
                "tier": "green",
                "evidence_status": "supported",
                "support_relation_status": "supported",
                "original_text_verified": True,
                "requires_manual_review": False,
            }],
            "cross_checks": [],
            "issues": [{
                "code": "MODEL_TIMEOUT",
                "agent": "finance",
                "window_id": "finance-2",
                "detail": "供应商返回的任意正文不得持久化",
            }],
            "coverage": {"planned": 2, "completed": 1},
        }

    monkeypatch.setattr(runner, "audit_contract", fake_audit)

    result = run_audit(
        db,
        contract,
        generation=4,
        batch_item_id=item.id,
        execution_token="partial-token",
    )

    db.expire_all()
    saved_item = db.get(AuditBatchItem, item.id)
    snapshot = json.loads(saved_item.result_json)
    assert observed_generations == [4]
    assert result["status"] == saved_item.status == "review_required"
    assert result["risk_count"] == 1
    assert db.query(Risk).filter(Risk.contract_id == contract.id).count() == 1
    assert snapshot["quality_reasons"] == ["INCOMPLETE_COVERAGE", "MODEL_TIMEOUT"]
    assert snapshot["coverage"] == {"planned": 2, "completed": 1}
    assert snapshot["issues"][0]["detail"] == "模型调用超时"
    assert "供应商返回" not in saved_item.result_json


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
    assert lock_calls == 3
    assert commits == 3


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


@pytest.mark.parametrize("audit_job_id", [None, 12])
def test_window_calls_have_one_log_each_and_only_jobs_persist_checkpoints(
    monkeypatch, db: Session, audit_job_id,
):
    from app.llm.base import LLMResponse
    from app.models.models import AuditWindowRun, LLMCallLog
    from app.services.audit import auditor
    from app.services.audit.window_repository import SqlAlchemyWindowCheckpoint

    contract = _contract(db, "window-log.txt")
    contract_id = contract.id
    db.commit()
    factory = sessionmaker(bind=db.get_bind())
    calls = []

    class Adapter:
        def chat(self, *_args, **_kwargs):
            calls.append(1)
            return LLMResponse(
                text='{"risks": [], "has_more": false}', model="test",
                prompt_tokens=10, completion_tokens=5,
            )

    monkeypatch.setattr(auditor, "get_llm_adapter", lambda: Adapter())
    monkeypatch.setattr(auditor, "retrieve", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        auditor, "SqlAlchemyWindowCheckpoint",
        lambda: SqlAlchemyWindowCheckpoint(session_factory=factory),
    )
    progress_runs = []
    for _ in range(2):
        progress_events = []
        result = auditor.audit_contract(
            {}, "第一条 合同正文", contract_id=contract_id, dimensions=["legal"],
            audit_job_id=audit_job_id, audit_generation=7,
            progress_callback=lambda value, stage: progress_events.append((value, stage)),
        )
        progress_runs.append(progress_events)
    logs = db.query(LLMCallLog).all()
    assert len(logs) == len(calls) == (2 if audit_job_id is None else 1)
    assert all(row.validation_status == "valid" for row in logs)
    assert all(row.contract_id == contract_id for row in logs)
    assert all(row.window_id and row.dimension == "legal" for row in logs)
    windows = db.query(AuditWindowRun).all()
    assert len(windows) == (0 if audit_job_id is None else 1)
    if windows:
        assert windows[0].audit_generation == 7
    assert result["coverage"] == {"planned": 1, "completed": 1}
    assert progress_runs == [
        [(75, "reviewing"), (82, "verifying"), (90, "verifying")],
        [(75, "reviewing"), (82, "verifying"), (90, "verifying")],
    ]


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
        if commits == 2:
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
    assert db.get(AuditBatchItem, item.id).status == "validating"


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
