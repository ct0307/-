"""单条风险法规证据链契约。"""
import json
import pytest

from app.llm.base import LLMResponse
from app.services.audit import auditor
from app.services.audit.evidence import bind_risk_evidence, build_evidence_query
from app.services.audit.protocol import ReviewIssue


@pytest.mark.parametrize("text,finish_reason,code", [
    ("not json", "stop", "INVALID_MODEL_OUTPUT"),
    ("[]", "length", "OUTPUT_TRUNCATED"),
])
def test_failed_window_has_issues_and_no_fabricated_risk(monkeypatch, text, finish_reason, code):
    class Adapter:
        def chat(self, *_args, **_kwargs):
            return LLMResponse(text=text, model="test", finish_reason=finish_reason)
    monkeypatch.setattr(auditor, "get_llm_adapter", lambda: Adapter())
    monkeypatch.setattr(auditor, "retrieve", lambda *_args, **_kwargs: [])
    result = auditor.audit_contract({}, "不可拆分合同正文", dimensions=["legal"])
    assert result["risks"] == []
    assert [issue["code"] for issue in result["issues"]] == [code]
    assert result["coverage"] == {"planned": 1, "completed": 0}


@pytest.mark.parametrize("quote,verified", [
    ("验收后支付全部款项", True),
    ("（全文未检出）", False),
    ("不存在的合同原文", False),
    ("验收 后支付全部款项", False),
])
def test_candidate_quote_is_exactly_located_and_unresolved_quotes_have_issue(monkeypatch, quote, verified):
    class Adapter:
        def chat(self, *_args, **_kwargs):
            return LLMResponse(text=json.dumps({"risks": [{
                "level": "medium", "category": "付款期限", "quote": quote,
                "reason": "付款条件需要进一步核验", "suggestion": "补充明确付款条件",
            }], "has_more": False}, ensure_ascii=False), model="test")
    monkeypatch.setattr(auditor, "get_llm_adapter", lambda: Adapter())
    monkeypatch.setattr(auditor, "retrieve", lambda *_args, **_kwargs: [])
    result = auditor.audit_contract({}, "第一条 验收后支付全部款项。", dimensions=["payment"])
    risk = result["risks"][0]
    assert risk["original_text_verified"] is verified
    assert risk["source_window_id"].startswith("window-")
    assert risk["source_clause_ids"] == ["第一条"]
    unresolved = [issue for issue in result["issues"] if issue["code"] == "ORIGINAL_TEXT_UNRESOLVED"]
    assert bool(unresolved) is (not verified)
    assert result["coverage"] == {"planned": 1, "completed": 1}


def test_agent_failure_preserves_other_agents_verified_risk_and_shared_context(monkeypatch):
    calls = []
    class Adapter:
        def chat(self, system, user, **kwargs):
            calls.append((system, user, kwargs))
            if "你是财务" in system:
                return LLMResponse(text="invalid json", model="test")
            return LLMResponse(text=json.dumps({"risks": [{
                "level": "high", "category": "关联交易", "quote": "关联方提供服务",
                "reason": "关联方交易需检查价格公允性", "suggestion": "明确价格公允性证明",
            }], "has_more": False}, ensure_ascii=False), model="test")
    monkeypatch.setattr(auditor, "get_llm_adapter", lambda: Adapter())
    monkeypatch.setattr(auditor, "retrieve", lambda *_args, **_kwargs: [])
    result = auditor.audit_contract({}, "第一条 关联方提供服务。")
    assert len(result["risks"]) == 1
    assert result["risks"][0]["original_text_verified"] is True
    assert result["risks"][0]["tier"] == "red"
    assert result["coverage"] == {"planned": 2, "completed": 1}
    assert any(issue["code"] == "INVALID_MODEL_OUTPUT" for issue in result["issues"])
    assert "结构化 Claims" in calls[1][1] and "关联交易" in calls[1][1]
    assert "严格的 JSON 对象" in calls[0][0]
    assert "has_more" in calls[0][0] and "最多5条" in calls[0][0]
    assert "第1页" in calls[0][1]
    assert calls[0][2]["options"].response_format == {"type": "json_object"}


def test_risk_evidence_query_contains_category_and_original_text():
    assert build_evidence_query("违约金过高", "每日按合同金额的1%计收") == (
        "违约金过高 每日按合同金额的1%计收"
    )


def test_risk_evidence_query_limits_untrusted_original_text():
    query = build_evidence_query("付款风险", "甲" * 500)

    assert query.startswith("付款风险 ")
    assert len(query.removeprefix("付款风险 ")) == 240


def test_each_risk_binds_its_own_retrieved_sources():
    queries: list[tuple[str, int]] = []

    def fake_search(query: str, *, top_k: int):
        queries.append((query, top_k))
        return [{"content": "约定违约金过高时可以适当减少。", "source": "民法典第585条", "score": 0.9}]

    risk = {"category": "违约金过高", "original_text": "每日按合同金额的1%计收"}
    result = bind_risk_evidence(risk, search=fake_search, top_k=2)

    assert queries == [("违约金过高 每日按合同金额的1%计收", 2)]
    assert result["rag_sources"][0]["source"] == "民法典第585条"
    assert "民法典第585条" in result["basis"]


def test_missing_evidence_requires_manual_review():
    risk = {"category": "未知风险", "original_text": "未知条款"}

    result = bind_risk_evidence(risk, search=lambda *_args, **_kwargs: [])

    assert result["rag_sources"] == []
    assert "人工复核" in result["basis"]


def test_selected_dimensions_are_enforced_in_agent_prompt(monkeypatch):
    captured: list[str] = []

    class Adapter:
        def chat(self, system: str, _user: str, **_kwargs) -> LLMResponse:
            captured.append(system)
            return LLMResponse(text='{"risks": [], "has_more": false}', model="test")

    monkeypatch.setattr(auditor, "get_llm_adapter", lambda: Adapter())
    monkeypatch.setattr(auditor, "retrieve", lambda *_args, **_kwargs: [])

    auditor._agent_audit(
        "legal",
        {},
        "合同正文",
        {"elements": {}},
        dimensions=["confidentiality"],
    )

    assert "本次仅审查以下维度：保密条款审查" in captured[0]


def test_confidentiality_dimension_runs_legal_agent(monkeypatch):
    calls: list[str] = []

    def fake_agent(role, *_args, **_kwargs):
        calls.append(role)
        return auditor.AgentAuditResult([], [], 1, 1)

    monkeypatch.setattr(auditor, "_agent_audit", fake_agent)

    auditor.audit_contract({}, "合同正文", dimensions=["confidentiality"])

    assert calls == ["legal"]


def test_prompt_leaves_formal_basis_to_grounding(monkeypatch):
    captured: list[str] = []

    class Adapter:
        def chat(self, system: str, _user: str, **_kwargs) -> LLMResponse:
            captured.append(system)
            return LLMResponse(text='{"risks": [], "has_more": false}', model="test")

    monkeypatch.setattr(auditor, "get_llm_adapter", lambda: Adapter())
    monkeypatch.setattr(auditor, "retrieve", lambda *_args, **_kwargs: [])

    auditor._agent_audit("legal", {}, "合同正文", {"elements": {}})

    assert "basis(依据来源)" not in captured[0]
    assert "reason(风险原因)" in captured[0]
    assert "confidence(0-100" not in captured[0]


def test_truncated_model_output_is_rejected(monkeypatch):
    class Adapter:
        def chat(self, _system: str, _user: str, **_kwargs) -> LLMResponse:
            return LLMResponse(text='{"risks": [], "has_more": false}', model="test", finish_reason="length")

    monkeypatch.setattr(auditor, "get_llm_adapter", lambda: Adapter())
    monkeypatch.setattr(auditor, "retrieve", lambda *_args, **_kwargs: [])

    result = auditor._agent_audit("legal", {}, "合同正文", {"elements": {}})
    assert result.risks == []
    assert result.issues[0].code == "OUTPUT_TRUNCATED"
    assert (result.planned, result.completed) == (1, 0)


def test_auditor_reports_agent_and_grounding_timings(monkeypatch):
    monkeypatch.setattr(auditor, "_agent_audit", lambda *_args, **_kwargs: auditor.AgentAuditResult([], [], 1, 1))

    result = auditor.audit_contract({}, "sensitive contract body", contract_id=42)

    assert set(result["timings"]) == {
        "legal_agent_ms",
        "finance_agent_ms",
        "grounding_ms",
    }
    assert all(isinstance(value, int) and value >= 0 for value in result["timings"].values())


def test_long_contract_is_audited_in_clause_windows_without_tail_truncation(monkeypatch):
    prompts: list[str] = []

    class Adapter:
        def chat(self, _system: str, user: str, **_kwargs) -> LLMResponse:
            prompts.append(user)
            return LLMResponse(text='{"risks": [], "has_more": false}', model="test")

    contract_text = "\n".join(
        f"第{index}条 " + (f"条款{index}内容" * 90)
        for index in range(1, 31)
    )
    monkeypatch.setattr(auditor, "get_llm_adapter", lambda: Adapter())
    monkeypatch.setattr(auditor, "retrieve", lambda *_args, **_kwargs: [])

    auditor._agent_audit("legal", {}, contract_text, {"elements": {}})

    assert len(prompts) > 1
    assert any("第30条" in prompt for prompt in prompts)
    assert all("审查窗口" in prompt for prompt in prompts)


def test_finance_agent_receives_structured_legal_claims(monkeypatch):
    prompts: list[str] = []

    class Adapter:
        def chat(self, _system: str, user: str, **_kwargs) -> LLMResponse:
            prompts.append(user)
            return LLMResponse(text='{"risks": [], "has_more": false}', model="test")

    legal_risks = [{
        "claim_id": "C-LEGAL-001",
        "category": "付款条件不明确",
        "level": "high",
        "original_text": "验收后付款",
        "risk_reason": "未约定验收期限",
        "evidence_ids": ["LAW-585", "DOC-8.2"],
        "evidence_status": "supported",
    }]
    shared_context = {
        "elements": {},
        "legal": auditor._summarize_for_context("legal", legal_risks, {}),
    }
    monkeypatch.setattr(auditor, "get_llm_adapter", lambda: Adapter())
    monkeypatch.setattr(auditor, "retrieve", lambda *_args, **_kwargs: [])

    auditor._agent_audit("finance", {}, "第一条 验收后付款。", shared_context)

    assert '"claim_id": "C-LEGAL-001"' in prompts[0]
    assert '"evidence_ids": ["LAW-585", "DOC-8.2"]' in prompts[0]


def test_audit_contract_runs_secondary_after_grounding_and_conflict_detection(monkeypatch):
    grounded = {
        **auditor._normalize({
            "level": "medium",
            "category": "付款期限冲突",
            "original_text": "验收后十日内付款",
            "risk_reason": "同一付款条件存在不同期限",
            "suggestion": "统一付款期限",
        }, "legal"),
        "claim_id": "C-PIPELINE-001",
        "evidence_ids": ["EV-LAW-001"],
        "rag_sources": [{
            "content": "付款期限应当明确。", "source": "付款规则", "reliable": True,
        }],
        "evidence_status": "supported",
        "support_relation_status": "supported",
        "original_text_verified": True,
        "requires_manual_review": False,
        "source_window_id": "window-1",
        "source_clause_ids": ["第一条"],
    }
    monkeypatch.setattr(
        auditor,
        "_agent_audit",
        lambda *_args, **_kwargs: auditor.AgentAuditResult([grounded.copy()], [], 1, 1),
    )
    monkeypatch.setattr(
        auditor,
        "detect_conflicts",
        lambda *_args, **_kwargs: [{
            "id": "X-1", "verdict": "conflict", "category": "付款期限冲突",
            "claim_ids": ["C-PIPELINE-001"],
        }],
    )
    monkeypatch.setattr(auditor, "build_logic_cross_checks", lambda _text: [])

    class Adapter:
        def chat(self, _system, _user, **_kwargs):
            return LLMResponse(text=json.dumps({"decisions": [{
                "claim_id": "C-PIPELINE-001",
                "verdict": "conflict",
                "reason_code": "EVIDENCE_CONFLICT",
                "evidence_ids": ["EV-LAW-001"],
            }]}), model="secondary-test")

    monkeypatch.setattr(auditor, "get_llm_adapter", lambda: Adapter())

    result = auditor.audit_contract(
        {}, "第一条 验收后十日内付款。", dimensions=["legal"]
    )

    assert len(result["risks"]) == 1
    assert result["risks"][0]["secondary_review_status"] == "conflict"
    assert "SECONDARY_REVIEW_CONFLICT" in [issue["code"] for issue in result["issues"]]


def test_rejected_secondary_candidate_does_not_leave_candidate_quality_issue(monkeypatch):
    candidate = {
        **auditor._normalize({
            "level": "medium",
            "category": "付款期限风险",
            "original_text": "验收后十日内付款",
            "risk_reason": "付款期限需要进一步核验",
            "suggestion": "明确付款期限",
        }, "legal"),
        "claim_id": "C-REJECT-PIPELINE",
        "evidence_ids": ["EV-LAW-001"],
        "rag_sources": [{
            "content": "付款期限应当明确。", "source": "付款规则", "reliable": True,
        }],
        "evidence_status": "partially_supported",
        "support_relation_status": "unclear",
        "original_text_verified": True,
        "source_window_id": "window-1",
        "source_clause_ids": ["第一条"],
    }
    monkeypatch.setattr(
        auditor,
        "_agent_audit",
        lambda *_args, **_kwargs: auditor.AgentAuditResult(
            [candidate.copy()],
            [ReviewIssue(
                code="EVIDENCE_UNRESOLVED",
                agent="legal",
                window_id="window-1",
                detail="候选证据需要进一步核验",
            )],
            1,
            1,
        ),
    )
    monkeypatch.setattr(auditor, "detect_conflicts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(auditor, "build_logic_cross_checks", lambda _text: [])

    class Adapter:
        def chat(self, _system, _user, **_kwargs):
            return LLMResponse(text=_secondary_reject(), model="secondary-test")

    def _secondary_reject():
        return json.dumps({"decisions": [{
            "claim_id": "C-REJECT-PIPELINE",
            "verdict": "reject",
            "reason_code": "EVIDENCE_DOES_NOT_SUPPORT_CANDIDATE",
            "evidence_ids": ["EV-LAW-001"],
        }]})

    monkeypatch.setattr(auditor, "get_llm_adapter", lambda: Adapter())

    result = auditor.audit_contract(
        {}, "第一条 验收后十日内付款。", dimensions=["legal"]
    )

    assert result["risks"] == []
    assert result["issues"] == []


def test_normalized_claim_id_is_stable_and_role_scoped():
    risk = {
        "level": "medium",
        "category": "付款条件不明确",
        "original_text": "验收后付款",
        "risk_reason": "未约定验收期限",
        "suggestion": "补充验收期限",
    }

    first = auditor._normalize(risk, "legal")
    second = auditor._normalize(risk, "legal")
    finance = auditor._normalize(risk, "finance")

    assert first["claim_id"] == second["claim_id"]
    assert first["claim_id"].startswith("C-")
    assert first["claim_id"] != finance["claim_id"]
    assert first["claim_status"] == "pending_evidence"


@pytest.mark.parametrize("across_pages", [False, True])
@pytest.mark.parametrize("quotes", [("pay now", "paynow"), ("paynow", "pay now")])
def test_whitespace_variants_keep_verified_quote_and_shared_claim(monkeypatch, across_pages, quotes):
    candidates = [{
        "level": "medium", "category": "付款期限", "quote": quote,
        "reason": "付款期限需要进一步核验", "suggestion": "补充明确付款期限",
    } for quote in quotes]
    pages = (
        [{"risks": [candidates[0]], "has_more": True},
         {"risks": [candidates[1]], "has_more": False}]
        if across_pages else [{"risks": candidates, "has_more": False}]
    )

    class Adapter:
        def chat(self, *_args, **_kwargs):
            return LLMResponse(text=json.dumps(pages.pop(0)), model="test")

    monkeypatch.setattr(auditor, "get_llm_adapter", lambda: Adapter())
    monkeypatch.setattr(auditor, "retrieve", lambda *_args, **_kwargs: [])
    result = auditor._agent_audit("legal", {}, "第一条 paynow", {"elements": {}})
    assert len(result.risks) == 1
    assert result.risks[0]["original_text"] == "paynow"
    assert result.risks[0]["original_text_verified"] is True
    assert not any(issue.code == "ORIGINAL_TEXT_UNRESOLVED" for issue in result.issues)
    expected_claim = auditor._normalize({"category": "付款期限", "original_text": "paynow"}, "legal")["claim_id"]
    shared = auditor._summarize_for_context("legal", result.risks, {})
    assert shared["claims"][0]["claim_id"] == expected_claim
    assert shared["claims"][0]["original_text"] == "paynow"
    assert result.planned == result.completed == 1
