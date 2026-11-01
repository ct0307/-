"""核验元数据与人工复核的持久化、输出和调用门禁。"""
import json
from datetime import datetime
from types import SimpleNamespace
from io import BytesIO

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints import risks, chat
from app.db.session import Base
from app.models.models import AuditLog, Contract, Risk, User
from app.schemas.contract import RiskOut, RiskStatusUpdate
from app.services.audit.decision import RiskDecision, apply_risk_decision
from app.services.masking import apply_risk_masking
from app.services.report.exporter import build_report_snapshot
from app.services.report.renderers import export_report_docx, export_report_xlsx


@pytest.fixture
def data():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(username="reviewer", password_hash="x", role="legal", department="法务")
        db.add(user)
        db.flush()
        contract = Contract(filename="合成测试.txt", storage_path="unused", department="法务", uploaded_by=user.id)
        db.add(contract)
        db.flush()
        trace = {"evidence_validation": {"mode": "deterministic", "version": "support-deterministic-v1", "failed_stage": "facts", "reason_code": "DETERMINISTIC_RULE_NOT_PROVEN"}}
        risk = Risk(contract_id=contract.id, level="high", category="付款风险", original_text="验收后付款", basis="未核验", suggestion="复核",
                    decision_trace_json=json.dumps(trace), support_validation_failed_stage="facts",
                    support_validator_version="support-deterministic-v1",
                    support_validation_reason_code="DETERMINISTIC_RULE_NOT_PROVEN")
        db.add(risk)
        db.commit()
        yield db, user, risk
    engine.dispose()


def test_decision_preserves_validation_and_other_trace_without_mutating_input():
    risk = {"decision_trace": {"evidence_validation": {"mode": "deterministic"}, "custom": 1}}
    result = apply_risk_decision(risk, RiskDecision("manual_review", ("EVIDENCE_UNRESOLVED",)))
    assert result["decision_trace"]["evidence_validation"] == {"mode": "deterministic"}
    assert result["decision_trace"]["custom"] == 1
    assert "status" not in risk["decision_trace"]


def test_human_review_is_readable_in_api_masking_and_report(data):
    db, user, risk = data
    response = risks.update_risk_status(risk.id, RiskStatusUpdate(review_status="confirmed", review_comment="已核对原件，仍需法务判断依据"), db, user)
    trace = json.loads(risk.decision_trace_json)
    review = trace["human_review"]
    assert review["operator_id"] == user.id
    assert review["reason"] == "已核对原件，仍需法务判断依据"
    assert review["status"] == "confirmed"
    assert datetime.fromisoformat(review["reviewed_at"]).tzinfo is not None
    assert response["human_review"] == review
    assert "evidence_validation" in trace
    assert risk.support_relation_status == "unclear"
    assert risk.evidence_status != "supported"
    assert db.query(AuditLog).filter_by(action="update_risk").count() == 1
    for row in (RiskOut.model_validate(risk).model_dump(), RiskOut.model_validate(apply_risk_masking(risk, "business")).model_dump(), build_report_snapshot(db)["risks"][0]):
        assert row["support_validation_mode"] == "deterministic"
        assert row["support_validation_failed_stage"] == "facts"
        assert row["support_validation_reason_code"] == "DETERMINISTIC_RULE_NOT_PROVEN"
        assert row["decision_trace"]["human_review"] == review


def test_failed_review_commit_rolls_back_status_trace_and_log(data, monkeypatch):
    db, user, risk = data
    old_status, old_trace, risk_id = risk.review_status, risk.decision_trace_json, risk.id
    monkeypatch.setattr(db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("模拟提交失败")))
    with pytest.raises(RuntimeError):
        risks.update_risk_status(risk_id, RiskStatusUpdate(review_status="ignored", review_comment="证据不支持该风险"), db, user)
    db.expire_all()
    assert db.get(Risk, risk_id).review_status == old_status
    assert db.get(Risk, risk_id).decision_trace_json == old_trace
    assert db.query(AuditLog).count() == 0


def _verified(**changes):
    risk = {"evidence_status": "supported", "support_relation_status": "supported", "support_validator_version": "support-deterministic-v1", "original_text_verified": True,
            "original_text": "验收后付款",
            "support_validation_failed_stage": "none", "support_validation_reason_code": "EVIDENCE_SUPPORTS_CLAIM",
            "evidence_ids": ["KC-1"], "rag_sources": [{"source": "中华人民共和国民法典", "content": "法条原文", "reliable": True, "applicability_status": "applicable"}]}
    risk.update(changes)
    return risk


def test_current_evidence_gate_accepts_finite_rules_and_rejects_legacy_and_bad_sources():
    from app.services.audit.evidence_state import is_current_evidence_verified
    assert is_current_evidence_verified(_verified())
    for changes in ({"original_text": ""}, {"support_validator_version": "rules-v2"}, {"support_validation_failed_stage": "facts"}, {"support_validation_reason_code": "DETERMINISTIC_RULE_NOT_PROVEN"}, {"evidence_ids": []}, {"evidence_ids": "not-json"}, {"original_text_verified": False}, {"rag_sources": [{}]}, {"evidence_status": "unclear"}):
        assert not is_current_evidence_verified(_verified(**changes))


def test_chat_uses_the_same_current_evidence_gate(data, monkeypatch):
    db, user, risk = data
    for key, value in _verified().items():
        setattr(risk, "evidence_ids_json" if key == "evidence_ids" else key, json.dumps(value) if isinstance(value, list) else value)
    db.commit()
    class Adapter:
        def chat(self, *_args, **_kwargs):
            return SimpleNamespace(text=json.dumps({"reply": "依据已提供", "evidence_ids": ["KC-1"], "unresolved": []}), model="test", prompt_tokens=1, completion_tokens=1, latency_ms=1)
    monkeypatch.setattr(chat, "get_llm_adapter", lambda: Adapter())
    response = chat.chat_with_risk(chat.ChatRequest(risk_id=risk.id, message="解释原文"), db, user)
    assert response.state == "ANSWERED"
    assert response.references[0]["evidence_id"] == "KC-1"
    assert build_report_snapshot(db)["summary"]["supported"] == 1


@pytest.mark.parametrize('output', [
    '未按结构作答',
    json.dumps({"reply": "结论", "evidence_ids": ["伪造编号"], "unresolved": []}),
    json.dumps({"reply": "结论", "evidence_ids": [], "unresolved": []}),
    json.dumps({"reply": "结论", "evidence_ids": ["KC-1"], "unresolved": [], "extra": True}),
    json.dumps({"reply": "依据《虚构法规》第999条", "evidence_ids": ["KC-1"], "unresolved": []}),
])
def test_chat_rejects_invalid_generated_answers(data, monkeypatch, output):
    db, user, risk = data
    for key, value in _verified().items():
        setattr(risk, "evidence_ids_json" if key == "evidence_ids" else key, json.dumps(value) if isinstance(value, list) else value)
    db.commit()
    class Adapter:
        def chat(self, *_args, **kwargs):
            assert kwargs['options'].max_output_tokens <= 800
            return SimpleNamespace(text=output, model="test", prompt_tokens=1, completion_tokens=1, latency_ms=1)
    monkeypatch.setattr(chat, "get_llm_adapter", lambda: Adapter())
    response = chat.chat_with_risk(chat.ChatRequest(risk_id=risk.id, message="解释原文"), db, user)
    assert response.state == "MANUAL_REVIEW"
    assert response.references == []
    assert '伪造编号' not in response.reply


def test_chat_reports_only_used_references_and_unresolved_items(data, monkeypatch):
    db, user, risk = data
    for key, value in _verified().items():
        setattr(risk, "evidence_ids_json" if key == "evidence_ids" else key, json.dumps(value) if isinstance(value, list) else value)
    db.commit()
    class Adapter:
        def chat(self, *_args, **_kwargs):
            return SimpleNamespace(text=json.dumps({"reply": "无法判断", "evidence_ids": [], "unresolved": ["缺少履约事实"]}), model="test", prompt_tokens=1, completion_tokens=1, latency_ms=1)
    monkeypatch.setattr(chat, "get_llm_adapter", lambda: Adapter())
    response = chat.chat_with_risk(chat.ChatRequest(risk_id=risk.id, message="解释原文"), db, user)
    assert response.state == "MANUAL_REVIEW"
    assert response.references == []
    assert "缺少履约事实" in response.reply


def test_chat_lists_only_actually_used_evidence(data, monkeypatch):
    db, user, risk = data
    value = _verified(evidence_ids=['KC-1', 'KC-2'])
    value['rag_sources'] *= 2
    for key, item in value.items():
        setattr(risk, 'evidence_ids_json' if key == 'evidence_ids' else key, json.dumps(item) if isinstance(item, list) else item)
    db.commit()
    class Adapter:
        def chat(self, *_args, **_kwargs):
            return SimpleNamespace(text=json.dumps({'reply': '请核对原文', 'evidence_ids': ['KC-2', 'KC-2'], 'unresolved': []}),
                                   model='test', prompt_tokens=1, completion_tokens=1, latency_ms=1)
    monkeypatch.setattr(chat, 'get_llm_adapter', lambda: Adapter())
    result = chat.chat_with_risk(chat.ChatRequest(risk_id=risk.id, message='解释'), db, user)
    assert result.state == 'ANSWERED'
    assert result.references == [{'evidence_id': 'KC-2', 'kind': 'historical_audit'}]


def test_chat_context_budget_blocks_model_call(data, monkeypatch):
    db, user, risk = data
    for key, value in _verified(original_text='合成原文' * 7000).items():
        setattr(risk, 'evidence_ids_json' if key == 'evidence_ids' else key, json.dumps(value) if isinstance(value, list) else value)
    db.commit()
    monkeypatch.setattr(chat, 'get_llm_adapter', lambda: pytest.fail('超限上下文不得调用模型'))
    result = chat.chat_with_risk(chat.ChatRequest(risk_id=risk.id, message='解释'), db, user)
    assert result.state == 'CONTEXT_LIMIT'
    assert result.references == []


def test_truncated_structured_chat_answer_is_not_accepted(data, monkeypatch):
    db, user, risk = data
    for key, value in _verified().items():
        setattr(risk, 'evidence_ids_json' if key == 'evidence_ids' else key, json.dumps(value) if isinstance(value, list) else value)
    db.commit()
    class Adapter:
        def chat(self, *_args, **_kwargs):
            return SimpleNamespace(text=json.dumps({'reply': '解释', 'evidence_ids': ['KC-1'], 'unresolved': []}),
                                   finish_reason='length', model='test', prompt_tokens=1, completion_tokens=1, latency_ms=1)
    monkeypatch.setattr(chat, 'get_llm_adapter', lambda: Adapter())
    result = chat.chat_with_risk(chat.ChatRequest(risk_id=risk.id, message='解释'), db, user)
    assert result.state == 'MANUAL_REVIEW'
    assert result.references == []


def test_word_and_excel_show_validation_metadata_and_actual_human_review(data):
    from docx import Document
    from openpyxl import load_workbook
    db, user, risk = data
    risks.update_risk_status(risk.id, RiskStatusUpdate(review_status="confirmed", review_comment="本次人工核对意见"), db, user)
    snapshot = build_report_snapshot(db)
    doc = Document(BytesIO(export_report_docx(snapshot)))
    text = "\n".join(p.text for p in doc.paragraphs)
    wb = load_workbook(BytesIO(export_report_xlsx(snapshot)))
    excel_text = "\n".join(str(c.value) for sheet in wb for row in sheet for c in row)
    for rendered in (text, excel_text):
        assert "本次人工核对意见" in rendered
        assert "support-deterministic-v1" in rendered
        assert "DETERMINISTIC_RULE_NOT_PROVEN" in rendered
        assert "操作人ID 1" in rendered


def test_excel_ledger_does_not_promote_legacy_supported_flag(data):
    from openpyxl import load_workbook
    db, _user, risk = data
    risk.evidence_status = "supported"
    risk.original_text_verified = True
    risk.support_validator_version = "rules-v2"
    db.commit()
    snapshot = build_report_snapshot(db)
    assert snapshot["summary"]["supported"] == 0
    wb = load_workbook(BytesIO(export_report_xlsx(snapshot)))
    assert wb["风险台账"]["K2"].value == "核验不确定 · 待人工复核"
