import json

from app.llm.base import LLMError, LLMResponse
from app.services.audit import auditor
from app.services.audit.protocol import ReviewIssue
from app.services.audit.result_quality import AuditCoverage, decide_audit_status
from app.services.audit.secondary_review import (
    SecondaryReviewer,
    apply_secondary_decisions,
    conflict_claim_ids,
)


def _risk(claim_id: str, **changes) -> dict:
    risk = {
        "claim_id": claim_id,
        "agent": "legal",
        "level": "medium",
        "category": "付款期限风险",
        "original_text": "验收后十日内付款",
        "risk_reason": "付款期限需要核验",
        "suggestion": "明确付款条件和期限",
        "evidence_status": "supported",
        "support_relation_status": "supported",
        "evidence_ids": ["EV-LAW-001"],
        "rag_sources": [{
            "content": "付款期限应当明确。",
            "source": "合同付款审查规则",
            "reliable": True,
        }],
        "source_window_id": "window-1",
        "source_clause_ids": ["第一条"],
        "original_text_verified": True,
        "requires_manual_review": False,
    }
    risk.update(changes)
    return risk


def _decision(claim_id: str, verdict: str = "confirm", **changes) -> str:
    reason_codes = {
        "confirm": "EVIDENCE_SUPPORTS_CANDIDATE",
        "reject": "EVIDENCE_DOES_NOT_SUPPORT_CANDIDATE",
        "conflict": "EVIDENCE_CONFLICT",
    }
    decision = {
        "claim_id": claim_id,
        "verdict": verdict,
        "reason_code": reason_codes[verdict],
        "evidence_ids": ["EV-LAW-001"],
    }
    decision.update(changes)
    return json.dumps({"decisions": [decision]}, ensure_ascii=False)


class QueueAdapter:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, str, object]] = []

    def chat(self, system, user, *, options=None, **_kwargs):
        self.calls.append((system, user, options))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return LLMResponse(text=response, model="secondary-test")


class CallRecorder:
    def __init__(self):
        self.calls: list[dict] = []

    def record_call(self, **values):
        self.calls.append(values)


def test_only_high_conflict_and_unclear_evidence_items_call_secondary_model():
    adapter = QueueAdapter([
        _decision("C-HIGH-001"),
        _decision("C-CONFLICT-001", "reject"),
        _decision("C-UNCLEAR-001"),
    ])
    reviewer = SecondaryReviewer(adapter)

    result = reviewer.review(
        risks=[
            _risk("C-LOW-OK01", level="low"),
            _risk("C-MEDIUM-OK"),
            _risk("C-HIGH-001", level="high"),
            _risk("C-CONFLICT-001"),
            _risk(
                "C-UNCLEAR-001",
                evidence_status="partially_supported",
                support_relation_status="unclear",
            ),
            _risk("C-NO-EVIDENCE", evidence_ids=[], rag_sources=[]),
        ],
        conflict_claim_ids={"C-CONFLICT-001"},
    )

    called_claims = [json.loads(user)["candidate"]["claim_id"] for _, user, _ in adapter.calls]
    assert called_claims == ["C-HIGH-001", "C-CONFLICT-001", "C-UNCLEAR-001"]
    assert result.by_claim["C-LOW-OK01"].status == "not_required"
    assert result.by_claim["C-MEDIUM-OK"].status == "not_required"
    assert result.by_claim["C-NO-EVIDENCE"].status == "manual_required"


def test_prompt_and_response_are_limited_to_authorized_candidate_and_evidence():
    adapter = QueueAdapter([_decision("C-HIGH-002")])
    risk = _risk(
        "C-HIGH-002",
        level="high",
        rag_sources=[
            {"content": "授权摘要", "source": "授权来源", "reliable": True},
            {"content": "不得发送的额外资料", "source": "额外来源", "reliable": True},
        ],
    )

    SecondaryReviewer(adapter).review(risks=[risk], conflict_claim_ids=set())

    system, user, options = adapter.calls[0]
    payload = json.loads(user)
    assert set(payload) == {"candidate", "contract_quote", "authorized_evidence"}
    assert set(payload["candidate"]) == {
        "claim_id", "agent", "level", "category", "risk_reason", "suggestion"
    }
    assert payload["contract_quote"] == "验收后十日内付款"
    assert payload["authorized_evidence"] == [{
        "evidence_id": "EV-LAW-001", "summary": "授权摘要", "source": "授权来源"
    }]
    assert "不得发送的额外资料" not in user
    assert "不得引入新法规" in system
    assert options.response_format == {"type": "json_object"}


def test_untrusted_secondary_evidence_id_becomes_manual_required():
    adapter = QueueAdapter([
        _decision("C-HIGH-003", evidence_ids=["EV-NOT-AUTHORIZED"])
    ])

    result = SecondaryReviewer(adapter).review(
        risks=[_risk("C-HIGH-003", level="high")],
        conflict_claim_ids=set(),
    )

    assert result.by_claim["C-HIGH-003"].status == "manual_required"


def test_secondary_free_text_reason_is_never_published():
    untrusted = "Civil Code section 999 proves a new fraud risk"
    adapter = QueueAdapter([_decision("C-HIGH-ARTICLE", reason=untrusted)])

    result = SecondaryReviewer(adapter).review(
        risks=[_risk("C-HIGH-ARTICLE", level="high")],
        conflict_claim_ids=set(),
    )

    assert result.by_claim["C-HIGH-ARTICLE"].status == "manual_required"
    assert untrusted not in result.by_claim["C-HIGH-ARTICLE"].reason


def test_unverified_contract_quote_requires_manual_review_without_model_call():
    adapter = QueueAdapter([])

    result = SecondaryReviewer(adapter).review(
        risks=[_risk("C-UNLOCATED-01", level="high", original_text_verified=False)],
        conflict_claim_ids=set(),
    )

    assert adapter.calls == []
    assert result.by_claim["C-UNLOCATED-01"].status == "manual_required"


def test_apply_decisions_removes_reject_and_keeps_conflict_with_issue():
    adapter = QueueAdapter([
        _decision("C-CONFIRM-01"),
        _decision("C-REJECT-001", "reject"),
        _decision("C-CONFLICT-02", "conflict"),
    ])
    risks = [
        _risk(
            "C-CONFIRM-01",
            level="high",
            evidence_status="partially_supported",
            support_relation_status="unclear",
            requires_manual_review=True,
        ),
        _risk("C-REJECT-001", level="high"),
        _risk("C-CONFLICT-02", level="high"),
        _risk("C-NO-EVIDENCE", evidence_ids=[], rag_sources=[]),
        _risk("C-LOW-OK02", level="low"),
    ]
    decisions = adapter and SecondaryReviewer(adapter).review(
        risks=risks, conflict_claim_ids=set()
    )

    published, issues = apply_secondary_decisions(risks, decisions)

    by_claim = {risk["claim_id"]: risk for risk in published}
    assert set(by_claim) == {
        "C-CONFIRM-01", "C-CONFLICT-02", "C-NO-EVIDENCE", "C-LOW-OK02"
    }
    assert by_claim["C-CONFIRM-01"]["secondary_review_status"] == "confirmed"
    assert by_claim["C-CONFIRM-01"]["evidence_status"] == "partially_supported"
    assert by_claim["C-CONFIRM-01"]["support_relation_status"] == "unclear"
    assert by_claim["C-CONFIRM-01"]["requires_manual_review"] is False
    assert by_claim["C-CONFIRM-01"]["claim_status"] == "accepted"
    assert by_claim["C-CONFLICT-02"]["secondary_review_status"] == "conflict"
    assert by_claim["C-NO-EVIDENCE"]["secondary_review_status"] == "manual_required"
    assert by_claim["C-LOW-OK02"]["secondary_review_status"] == "not_required"
    assert [issue.code for issue in issues] == ["SECONDARY_REVIEW_CONFLICT"]
    assert all(isinstance(issue, ReviewIssue) for issue in issues)


def test_timeout_only_marks_selected_candidate_and_records_safe_failure():
    timeout = LLMError("sensitive provider text", code="MODEL_TIMEOUT", retryable=True)
    adapter = QueueAdapter([timeout, _decision("C-HIGH-005")])
    recorder = CallRecorder()
    reviewer = SecondaryReviewer(adapter, recorder=recorder)

    result = reviewer.review(
        risks=[_risk("C-HIGH-004", level="high"), _risk("C-HIGH-005", level="high")],
        conflict_claim_ids=set(),
    )

    assert result.by_claim["C-HIGH-004"].status == "manual_required"
    assert result.by_claim["C-HIGH-005"].status == "confirmed"
    assert len(adapter.calls) == 2
    assert [call["agent"] for call in recorder.calls] == ["secondary", "secondary"]
    assert recorder.calls[0]["error_code"] == "MODEL_TIMEOUT"
    assert "sensitive provider text" not in repr(recorder.calls)


def test_secondary_items_share_deadline_and_do_not_start_after_expiry():
    from app.services.audit.secondary_review import SecondaryReviewer

    now = [0.0]

    class AdvancingAdapter(QueueAdapter):
        def chat(self, *args, **kwargs):
            response = super().chat(*args, **kwargs)
            now[0] = 2.0
            return response

    risks = [
        _risk(claim_id="C-FIRST-01", level="high"),
        _risk(claim_id="C-SECOND-01", level="high"),
    ]
    adapter = AdvancingAdapter([_decision("C-FIRST-01")])

    result = SecondaryReviewer(adapter, clock=lambda: now[0]).review(
        risks=risks,
        conflict_claim_ids=set(),
        deadline=1.0,
    )

    assert len(adapter.calls) == 1
    assert result.by_claim["C-FIRST-01"].status == "confirmed"
    assert result.by_claim["C-SECOND-01"].status == "manual_required"
    assert "时限" in result.by_claim["C-SECOND-01"].reason


def test_explicit_related_party_claim_is_selected_even_when_category_differs():
    risks = [_risk(
        "C-RELATED-001",
        category="供应商利益关联",
        level="medium",
    )]
    checks = [{
        "id": "X1",
        "verdict": "conflict",
        "category": "关联交易",
        "claim_ids": ["C-RELATED-001"],
    }]

    assert conflict_claim_ids(risks, checks) == {"C-RELATED-001"}


def test_cross_agent_conflict_emits_exact_related_party_claim_ids():
    risks = [
        _risk("C-RELATED-001", category="供应商利益关联"),
        _risk("C-UNRELATED-01", category="付款期限"),
    ]
    legal_context = auditor._summarize_for_context("legal", risks, {})
    assert legal_context["related_party_claim_ids"] == ["C-RELATED-001"]

    checks = auditor.detect_conflicts({
        "legal": legal_context,
        "finance": {},
    }, {})

    assert checks[0]["claim_ids"] == ["C-RELATED-001"]


def test_similar_payment_category_without_exact_relation_is_not_selected():
    risks = [_risk(
        "C-PAYMENT-NORMAL",
        category="付款",
        level="medium",
        source_clause_ids=["第三条"],
    )]
    checks = [{
        "id": "FC-1",
        "from": "system",
        "verdict": "conflict",
        "category": "付款比例异常",
        "evidence_clause_ids": ["第一条", "第二条"],
    }]

    assert conflict_claim_ids(risks, checks) == set()


def test_deterministic_conflict_uses_exact_clause_relation():
    risks = [
        _risk("C-PAYMENT-EXACT", source_clause_ids=["第二条"]),
        _risk("C-PAYMENT-OTHER", source_clause_ids=["第三条"]),
    ]
    checks = [{
        "id": "LC-1",
        "from": "system",
        "verdict": "conflict",
        "category": "完全不同类别",
        "evidence_clause_ids": ["第一条", "第二条"],
    }]

    assert conflict_claim_ids(risks, checks) == {"C-PAYMENT-EXACT"}


def test_risk_tier_uses_exact_conflict_claim_id_not_shared_category():
    conflict_ids = {"C-ACTUAL-CONFLICT"}

    actual = auditor.classify_tier(
        _risk("C-ACTUAL-CONFLICT", level="medium"), conflict_ids
    )
    similar = auditor.classify_tier(
        _risk("C-NOT-CONFLICT", level="medium"), conflict_ids
    )

    assert actual == "red"
    assert similar == "yellow"


def test_payee_mismatch_binds_exact_candidate_and_calls_secondary(monkeypatch):
    candidate = _risk(
        "C-PAYEE-MISMATCH",
        agent="finance",
        category="资金路径核验",
        original_text="本合同款项支付至第三方收款公司账户",
        level="medium",
    )
    monkeypatch.setattr(
        auditor,
        "_agent_audit",
        lambda *_args, **_kwargs: auditor.AgentAuditResult(
            [candidate.copy()], [], 1, 1
        ),
    )
    adapter = QueueAdapter([_decision("C-PAYEE-MISMATCH")])
    monkeypatch.setattr(auditor, "get_llm_adapter", lambda: adapter)

    result = auditor.audit_contract(
        {"payee": "第三方收款公司", "party_b": "合同乙方公司"},
        "第一条 本合同款项支付至第三方收款公司账户。",
        dimensions=["payment"],
    )

    x2 = next(check for check in result["cross_checks"] if check["id"] == "X2")
    assert x2["claim_ids"] == ["C-PAYEE-MISMATCH"]
    assert len(adapter.calls) == 1
    assert result["risks"][0]["secondary_review_status"] == "confirmed"


def test_unbound_payee_mismatch_requires_review_without_model_call(monkeypatch):
    monkeypatch.setattr(
        auditor,
        "_agent_audit",
        lambda *_args, **_kwargs: auditor.AgentAuditResult([], [], 1, 1),
    )
    adapter = QueueAdapter([])
    monkeypatch.setattr(auditor, "get_llm_adapter", lambda: adapter)

    result = auditor.audit_contract(
        {"payee": "第三方收款公司", "party_b": "合同乙方公司"},
        "第一条 合同正文。",
        dimensions=["payment"],
    )
    decision = decide_audit_status(
        result["risks"], result["issues"], AuditCoverage(**result["coverage"])
    )

    assert adapter.calls == []
    assert [issue["code"] for issue in result["issues"]] == ["UNBOUND_CONFLICT"]
    assert decision.status == "review_required"


def test_unbound_payment_schedule_conflict_requires_review_without_model_call(
    monkeypatch,
):
    monkeypatch.setattr(
        auditor,
        "_agent_audit",
        lambda *_args, **_kwargs: auditor.AgentAuditResult([], [], 1, 1),
    )
    adapter = QueueAdapter([])
    monkeypatch.setattr(auditor, "get_llm_adapter", lambda: adapter)

    result = auditor.audit_contract(
        {},
        "第一条 预付款为合同金额的50%。",
        dimensions=["payment"],
    )
    decision = decide_audit_status(
        result["risks"], result["issues"], AuditCoverage(**result["coverage"])
    )

    assert adapter.calls == []
    assert [issue["code"] for issue in result["issues"]] == ["UNBOUND_CONFLICT"]
    assert decision.status == "review_required"


def test_rejected_payee_candidate_leaves_unbound_conflict_for_review(monkeypatch):
    candidate = _risk(
        "C-PAYEE-REJECTED",
        agent="finance",
        category="资金路径核验",
        original_text="本合同款项支付至第三方收款公司账户。",
        level="medium",
    )
    monkeypatch.setattr(
        auditor,
        "_agent_audit",
        lambda *_args, **_kwargs: auditor.AgentAuditResult(
            [candidate.copy()], [], 1, 1
        ),
    )
    adapter = QueueAdapter([_decision("C-PAYEE-REJECTED", "reject")])
    monkeypatch.setattr(auditor, "get_llm_adapter", lambda: adapter)

    result = auditor.audit_contract(
        {"payee": "第三方收款公司", "party_b": "合同乙方公司"},
        "第一条 本合同款项支付至第三方收款公司账户。",
        dimensions=["payment"],
    )
    decision = decide_audit_status(
        result["risks"], result["issues"], AuditCoverage(**result["coverage"])
    )

    assert len(adapter.calls) == 1
    assert result["risks"] == []
    assert [issue["code"] for issue in result["issues"]] == ["UNBOUND_CONFLICT"]
    assert decision.status == "review_required"


def test_confirm_without_evidence_keeps_unclear_candidate_in_manual_review():
    risk = _risk(
        "C-CONFIRM-NO-EVIDENCE",
        level="high",
        evidence_status="partially_supported",
        support_relation_status="unclear",
        requires_manual_review=True,
    )
    adapter = QueueAdapter([
        _decision("C-CONFIRM-NO-EVIDENCE", evidence_ids=[])
    ])

    secondary_result = SecondaryReviewer(adapter).review(
        risks=[risk], conflict_claim_ids=set()
    )
    published, issues = apply_secondary_decisions([risk], secondary_result)
    decision = decide_audit_status(
        published, issues, AuditCoverage(planned=1, completed=1)
    )

    assert secondary_result.by_claim["C-CONFIRM-NO-EVIDENCE"].status == "manual_required"
    assert published[0]["requires_manual_review"] is True
    assert published[0]["claim_status"] == "manual_review"
    assert decision.status == "review_required"
