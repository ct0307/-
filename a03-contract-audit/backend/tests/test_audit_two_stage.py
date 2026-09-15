import json

from app.llm.base import LLMResponse
from app.services.rag.contract_structure import ContractWindow


def _response(payload: dict, *, finish_reason: str = "stop") -> LLMResponse:
    return LLMResponse(
        text=json.dumps(payload, ensure_ascii=False),
        model="test-model",
        finish_reason=finish_reason,
    )


class FakeAdapter:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, system, user, *, temperature=0.2, options=None):
        self.calls.append((system, user, temperature, options))
        return self.responses.pop(0)


def _finding(category: str, quote: str) -> dict:
    return {"level": "high", "category": category, "quote": quote}


def _detail(reason: str, suggestion: str) -> dict:
    return {"reason": reason, "suggestion": suggestion}


def _request(*, discovery_calls=None, detail_calls=None):
    from app.services.audit.review_pipeline import ReviewWindow, WindowReviewRequest

    discovery_calls = discovery_calls if discovery_calls is not None else []
    detail_calls = detail_calls if detail_calls is not None else []

    def build_discovery_prompt(review_window, page, dimensions, accepted, page_size):
        discovery_calls.append((review_window, page, dimensions, accepted, page_size))
        return f"page={page};page_size={page_size};accepted={len(accepted)}"

    def build_enrichment_prompt(review_window, finding, concise):
        detail_calls.append((review_window, finding, concise))
        return f"category={finding.category};concise={concise}"

    window = ContractWindow(
        window_id="window-root",
        clause_ids=("第一条", "第二条"),
        text="第一条 付款期限未约定。\n第二条 验收标准未约定。",
    )
    return WindowReviewRequest(
        contract_id="contract-7",
        audit_job_id="job-11",
        audit_generation=3,
        agent="legal",
        dimensions=("legal", "payment"),
        review_window=ReviewWindow(window),
        system_prompt="legacy",
        build_user_prompt=lambda *_args: "legacy",
        discovery_system_prompt="发现候选",
        build_discovery_prompt=build_discovery_prompt,
        enrichment_system_prompt="补全候选",
        build_enrichment_prompt=build_enrichment_prompt,
    )


def test_two_stage_review_pages_compact_findings_and_enriches_one_at_a_time():
    from app.services.audit.review_pipeline import WindowReviewer

    payment = _finding("付款风险", "第一条 付款期限未约定。")
    acceptance = _finding("验收风险", "第二条 验收标准未约定。")
    termination = _finding("解除风险", "合同未约定解除条件。")
    adapter = FakeAdapter([
        _response({"risks": [payment, acceptance], "has_more": True}),
        _response(_detail("付款时间不明确。", "补充明确付款日期。")),
        _response(_detail("验收标准不明确。", "补充可核验的验收标准。")),
        _response({"risks": [termination], "has_more": False}),
        _response(_detail("解除机制缺失。", "补充解除条件和通知期限。")),
    ])
    discovery_calls = []
    detail_calls = []

    result = WindowReviewer(adapter, max_pages=8).review(
        _request(discovery_calls=discovery_calls, detail_calls=detail_calls)
    )

    assert result.complete is True
    assert [candidate.category for candidate in result.candidates] == [
        "付款风险", "验收风险", "解除风险",
    ]
    assert [call[4] for call in discovery_calls] == [5, 5]
    assert discovery_calls[0][3] == ()
    assert [finding.category for finding in discovery_calls[1][3]] == [
        "付款风险", "验收风险",
    ]
    assert [call[1].category for call in detail_calls] == [
        "付款风险", "验收风险", "解除风险",
    ]
    assert all(call[2] is False for call in detail_calls)


def test_discovery_truncation_retries_one_candidate_before_splitting_window():
    from app.services.audit.review_pipeline import WindowReviewer

    payment = _finding("付款风险", "第一条 付款期限未约定。")
    adapter = FakeAdapter([
        _response({}, finish_reason="length"),
        _response({"risks": [payment], "has_more": False}),
        _response(_detail("付款时间不明确。", "补充明确付款日期。")),
    ])
    discovery_calls = []

    result = WindowReviewer(adapter).review(
        _request(discovery_calls=discovery_calls)
    )

    assert result.complete is True
    assert [candidate.category for candidate in result.candidates] == ["付款风险"]
    assert [call[4] for call in discovery_calls] == [5, 1]
    assert result.issues == []


def test_two_stage_disables_thinking_for_structured_audit_calls():
    from app.services.audit.review_pipeline import WindowReviewer

    payment = _finding("付款风险", "第一条 付款期限未约定。")
    adapter = FakeAdapter([
        _response({"risks": [payment], "has_more": False}),
        _response(_detail("付款时间不明确。", "补充明确付款日期。")),
    ])

    result = WindowReviewer(adapter).review(_request())

    assert result.complete is True
    assert all(call[3].thinking == "disabled" for call in adapter.calls)


def test_enrichment_truncation_retries_with_concise_prompt():
    from app.services.audit.review_pipeline import WindowReviewer

    payment = _finding("付款风险", "第一条 付款期限未约定。")
    adapter = FakeAdapter([
        _response({"risks": [payment], "has_more": False}),
        _response({}, finish_reason="length"),
        _response(_detail("期限不明。", "约定日期。")),
    ])
    detail_calls = []

    result = WindowReviewer(adapter).review(_request(detail_calls=detail_calls))

    assert result.complete is True
    assert result.candidates[0].reason == "期限不明。"
    assert [call[2] for call in detail_calls] == [False, True]
    assert result.issues == []
