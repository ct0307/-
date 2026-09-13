import json
from dataclasses import FrozenInstanceError

import pytest

from app.llm.base import LLMError, LLMResponse
from app.services.audit.protocol import AgentReviewResult
from app.services.rag.contract_structure import ContractWindow


def _risk(category="付款风险", quote="甲方应在验收后付款。"):
    return {
        "level": "high",
        "category": category,
        "quote": quote,
        "reason": "付款条件缺少足够履约保障。",
        "suggestion": "增加验收标准并保留合理尾款。",
    }


def _response(*, risks=None, has_more=False, finish_reason="stop", model="model-a"):
    return LLMResponse(
        text=json.dumps(
            {"risks": risks or [], "has_more": has_more}, ensure_ascii=False
        ),
        model=model,
        finish_reason=finish_reason,
    )


class FakeAdapter:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, system, user, *, temperature=0.2, options=None):
        self.calls.append((system, user, temperature, options))
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class MemoryCheckpoint:
    def __init__(self, cached=None):
        self.cached = cached
        self.loads = []
        self.saved = []
        self.records = []

    def load_valid(self, request):
        self.loads.append(request)
        return self.cached

    def save_valid(self, request, result):
        self.saved.append((request, result))

    def record_call(
        self,
        request,
        *,
        page,
        attempt,
        response,
        validation_status,
        error_code,
    ):
        self.records.append(
            {
                "request": request,
                "page": page,
                "attempt": attempt,
                "response": response,
                "validation_status": validation_status,
                "error_code": error_code,
            }
        )


def _window(text=None, window_id="window-root", clause_ids=None):
    return ContractWindow(
        window_id=window_id,
        clause_ids=clause_ids or ("第一条", "第二条"),
        text=text
        or "第一条 甲方应在验收后付款。\n第二条 乙方应按期完成交付。",
    )


def _request(window=None, prompt_calls=None):
    from app.services.audit.review_pipeline import ReviewWindow, WindowReviewRequest

    calls = prompt_calls if prompt_calls is not None else []

    def build_user_prompt(review_window, page, dimensions):
        calls.append((review_window, page, dimensions))
        return f"page={page}\n<contract>{review_window.window.text}</contract>"

    return WindowReviewRequest(
        contract_id="contract-7",
        audit_job_id="job-11",
        audit_generation=3,
        agent="legal",
        dimensions=("legal", "payment"),
        review_window=ReviewWindow(window or _window()),
        system_prompt="只输出严格 JSON。",
        build_user_prompt=build_user_prompt,
    )


def test_split_candidates_keep_leaf_provenance_through_json_round_trip():
    from app.services.audit.review_pipeline import WindowReviewer
    calls = []
    adapter = FakeAdapter([
        _response(finish_reason="length"),
        _response(risks=[_risk()]),
        _response(risks=[_risk("交付风险", "乙方应按期完成交付。")]),
    ])
    result = WindowReviewer(adapter).review(_request(prompt_calls=calls))
    restored = AgentReviewResult.model_validate_json(result.model_dump_json())
    assert [candidate.source_window_id for candidate in restored.candidates] == [
        call[0].window.window_id for call in calls[1:]
    ]
    assert [candidate.source_clause_ids for candidate in restored.candidates] == [["第一条"], ["第二条"]]


def test_real_window_retains_all_1025_system_clause_ids():
    from app.services.audit.review_pipeline import WindowReviewer
    from app.services.rag.contract_structure import build_contract_windows

    text = "\n".join(f"第{index}条 款" for index in range(1, 1026))
    windows = build_contract_windows(text, max_chars=16000)
    assert len(windows) == 1
    assert len(windows[0].clause_ids) == 1025
    adapter = FakeAdapter([_response(risks=[_risk(quote="第1025条 款")])])
    result = WindowReviewer(adapter).review(_request(window=windows[0]))
    restored = AgentReviewResult.model_validate_json(result.model_dump_json())
    assert restored.complete is True
    assert restored.candidates[0].source_clause_ids == list(windows[0].clause_ids)


def test_review_types_are_frozen_and_constructor_limits_are_validated():
    from app.services.audit.review_pipeline import ReviewWindow, WindowReviewer

    review_window = ReviewWindow(_window())
    with pytest.raises(FrozenInstanceError):
        review_window.depth = 1

    for kwargs in (
        {"max_split_depth": -1},
        {"max_pages": 0},
        {"max_call_attempts": 0},
    ):
        with pytest.raises(ValueError):
            WindowReviewer(FakeAdapter([]), **kwargs)


def test_valid_response_returns_complete_result_and_saves_checkpoint():
    from app.services.audit.review_pipeline import WindowReviewer

    checkpoint = MemoryCheckpoint()
    adapter = FakeAdapter([_response(risks=[_risk()])])

    result = WindowReviewer(adapter, checkpoint=checkpoint).review(_request())

    assert result.complete is True
    assert result.planned_windows == result.completed_windows == 1
    assert [risk.category for risk in result.candidates] == ["付款风险"]
    assert result.issues == []
    assert len(checkpoint.saved) == 1
    assert checkpoint.records[0]["validation_status"] == "valid"
    assert checkpoint.records[0]["error_code"] is None


def test_cached_complete_result_skips_adapter_and_prompt_builder():
    from app.services.audit.review_pipeline import WindowReviewer

    cached = AgentReviewResult(complete=True)
    checkpoint = MemoryCheckpoint(cached=cached)
    prompt_calls = []
    adapter = FakeAdapter([])

    result = WindowReviewer(adapter, checkpoint=checkpoint).review(
        _request(prompt_calls=prompt_calls)
    )

    assert result is cached
    assert adapter.calls == []
    assert prompt_calls == []
    assert checkpoint.saved == []
    assert checkpoint.records == []


def test_truncated_parent_reviews_only_its_children_at_depth_one():
    from app.services.audit.review_pipeline import WindowReviewer

    adapter = FakeAdapter([
        _response(finish_reason="length"),
        _response(),
        _response(),
    ])
    prompt_calls = []

    result = WindowReviewer(adapter).review(_request(prompt_calls=prompt_calls))

    assert result.complete is True
    assert result.planned_windows == result.completed_windows == 2
    assert [call[0].depth for call in prompt_calls] == [0, 1, 1]
    assert len({call[0].parent_window_id for call in prompt_calls[1:]}) == 1
    assert prompt_calls[1][0].parent_window_id == "window-root"


def test_failed_child_keeps_successful_sibling_candidate_and_leaf_progress():
    from app.services.audit.review_pipeline import WindowReviewer

    parent = _window(
        text="第一条 甲方应在验收后付款。\n第二条 乙方应按期完成交付。",
    )
    adapter = FakeAdapter([
        _response(finish_reason="length"),
        _response(risks=[_risk()]),
        _response(finish_reason="length"),
    ])

    result = WindowReviewer(adapter, max_split_depth=1).review(_request(parent))

    assert result.complete is False
    assert result.planned_windows == 2
    assert result.completed_windows == 1
    assert [risk.category for risk in result.candidates] == ["付款风险"]
    assert [issue.code for issue in result.issues] == ["OUTPUT_TRUNCATED"]


def test_unsplittable_truncation_returns_issue_without_fake_risk():
    from app.services.audit.review_pipeline import WindowReviewer

    atomic = _window(
        text="第一条 这是无法继续按完整边界拆分的条款。",
        clause_ids=("第一条",),
    )

    result = WindowReviewer(FakeAdapter([_response(finish_reason="length")])).review(
        _request(atomic)
    )

    assert result.complete is False
    assert result.planned_windows == 1
    assert result.completed_windows == 0
    assert result.candidates == []
    assert [issue.code for issue in result.issues] == ["OUTPUT_TRUNCATED"]


def test_later_page_truncation_keeps_valid_candidates_when_window_cannot_split():
    from app.services.audit.review_pipeline import WindowReviewer

    atomic = _window(
        text="第一条 这是无法继续按完整边界拆分的条款。",
        clause_ids=("第一条",),
    )
    adapter = FakeAdapter([
        _response(risks=[_risk()], has_more=True),
        _response(finish_reason="length"),
    ])

    result = WindowReviewer(adapter).review(_request(atomic))

    assert result.complete is False
    assert result.planned_windows == 1
    assert result.completed_windows == 0
    assert [candidate.category for candidate in result.candidates] == ["付款风险"]
    assert [issue.code for issue in result.issues] == ["OUTPUT_TRUNCATED"]


def test_later_page_truncation_merges_parent_candidates_with_partial_children():
    from app.services.audit.review_pipeline import WindowReviewer

    delivery_risk = _risk("交付风险", "乙方应按期完成交付。")
    parent_only_risk = _risk("验收风险", "验收标准由甲方另行通知。")
    adapter = FakeAdapter([
        _response(risks=[_risk(), parent_only_risk], has_more=True),
        _response(finish_reason="length"),
        _response(risks=[_risk(), delivery_risk]),
        _response(finish_reason="length"),
    ])

    result = WindowReviewer(adapter, max_split_depth=1).review(_request())

    assert result.complete is False
    assert result.planned_windows == 2
    assert result.completed_windows == 1
    assert [candidate.category for candidate in result.candidates] == [
        "付款风险",
        "验收风险",
        "交付风险",
    ]
    assert [issue.code for issue in result.issues] == ["OUTPUT_TRUNCATED"]


def test_invalid_json_gets_exactly_one_format_retry():
    from app.services.audit.review_pipeline import WindowReviewer

    checkpoint = MemoryCheckpoint()
    adapter = FakeAdapter([
        LLMResponse(text="not-json", model="model-a", finish_reason="stop"),
        LLMResponse(text="{} trailing", model="model-a", finish_reason="stop"),
    ])

    result = WindowReviewer(adapter, checkpoint=checkpoint).review(_request())

    assert len(adapter.calls) == 2
    assert result.complete is False
    assert result.candidates == []
    assert [issue.code for issue in result.issues] == ["INVALID_MODEL_OUTPUT"]
    assert [record["validation_status"] for record in checkpoint.records] == [
        "invalid",
        "invalid",
    ]


@pytest.mark.parametrize("content", [None, {"refusal": "cannot comply"}])
def test_openai_adapter_non_string_content_is_invalid_model_output(
    monkeypatch,
    content,
):
    from app.llm.adapters.openai_compatible import OpenAICompatibleAdapter
    from app.services.audit.review_pipeline import WindowReviewer

    calls = []

    def fake_post(_path, _payload, *, request_id=None):
        calls.append(request_id)
        return {
            "model": "model-a",
            "choices": [
                {
                    "message": {"content": content},
                    "finish_reason": "stop",
                }
            ],
        }, 1

    adapter = OpenAICompatibleAdapter(
        base_url="https://llm.example/v1",
        max_output_tokens=100,
    )
    monkeypatch.setattr(adapter, "_post", fake_post)
    checkpoint = MemoryCheckpoint()

    result = WindowReviewer(
        adapter,
        checkpoint=checkpoint,
        max_call_attempts=2,
    ).review(_request())

    assert len(calls) == 2
    assert result.complete is False
    assert result.candidates == []
    assert [issue.code for issue in result.issues] == ["INVALID_MODEL_OUTPUT"]
    assert [record["validation_status"] for record in checkpoint.records] == [
        "invalid",
        "invalid",
    ]


def test_pagination_stops_at_three_pages_and_deduplicates_without_model_id():
    from app.services.audit.review_pipeline import WindowReviewer

    duplicate = _risk()
    adapter = FakeAdapter([
        _response(risks=[duplicate], has_more=True, model="model-a"),
        _response(risks=[duplicate], has_more=True, model="model-b"),
        _response(risks=[_risk("交付风险", "乙方应按期完成交付。")], has_more=True),
    ])

    result = WindowReviewer(adapter, max_pages=3).review(_request())

    assert len(adapter.calls) == 3
    assert [risk.category for risk in result.candidates] == ["付款风险", "交付风险"]
    assert result.complete is False
    assert result.completed_windows == 0
    assert [issue.code for issue in result.issues] == ["PAGINATION_EXHAUSTED"]


def test_three_call_budget_sleeps_only_before_two_retry_calls():
    from app.services.audit.review_pipeline import WindowReviewer

    sleeps = []
    checkpoint = MemoryCheckpoint()
    adapter = FakeAdapter([
        LLMError("timeout", code="MODEL_TIMEOUT", retryable=True),
        LLMError("timeout", code="MODEL_TIMEOUT", retryable=True),
        LLMError("timeout", code="MODEL_TIMEOUT", retryable=True),
    ])

    result = WindowReviewer(
        adapter,
        checkpoint=checkpoint,
        sleep=sleeps.append,
    ).review(_request())

    assert len(adapter.calls) == 3
    assert sleeps == [0, 1]
    assert result.candidates == []
    assert [issue.code for issue in result.issues] == ["MODEL_TIMEOUT"]
    assert [record["attempt"] for record in checkpoint.records] == [1, 2, 3]
    assert all(record["validation_status"] == "error" for record in checkpoint.records)


def test_network_and_format_failures_share_three_call_budget_per_page():
    from app.services.audit.review_pipeline import WindowReviewer

    sleeps = []
    adapter = FakeAdapter([
        LLMError("timeout", code="MODEL_TIMEOUT", retryable=True),
        LLMError("timeout", code="MODEL_TIMEOUT", retryable=True),
        LLMResponse(text="not-json", model="model-a", finish_reason="stop"),
        _response(risks=[_risk()]),
    ])

    result = WindowReviewer(adapter, sleep=sleeps.append).review(_request())

    assert len(adapter.calls) == 3
    assert len(adapter.responses) == 1
    assert sleeps == [0, 1]
    assert result.complete is False
    assert result.candidates == []
    assert [issue.code for issue in result.issues] == ["INVALID_MODEL_OUTPUT"]


def test_non_retryable_model_rejection_is_safely_mapped_without_retry():
    from app.services.audit.review_pipeline import WindowReviewer

    adapter = FakeAdapter([
        LLMError("rejected", code="MODEL_REJECTED", retryable=False),
    ])

    result = WindowReviewer(adapter).review(_request())

    assert len(adapter.calls) == 1
    assert result.candidates == []
    assert [issue.code for issue in result.issues] == ["INVALID_MODEL_OUTPUT"]


def test_request_ids_are_stable_and_exclude_contract_body():
    from app.services.audit.protocol import AUDIT_JSON_FORMAT
    from app.services.audit.review_pipeline import WindowReviewer

    body = "第一条 SENSITIVE-CONTRACT-BODY。\n第二条 交付内容。"
    first_adapter = FakeAdapter([_response()])
    second_adapter = FakeAdapter([_response()])
    request = _request(_window(text=body))

    WindowReviewer(first_adapter).review(request)
    WindowReviewer(second_adapter).review(request)

    first_options = first_adapter.calls[0][3]
    second_options = second_adapter.calls[0][3]
    assert first_options.response_format == AUDIT_JSON_FORMAT
    assert first_options.request_id == second_options.request_id
    assert "SENSITIVE-CONTRACT-BODY" not in first_options.request_id
    assert all(
        token in first_options.request_id
        for token in ("job-11", "3", "legal", "window-root", "1", "1")
    )


def test_checkpoint_records_truncated_parent_and_saves_complete_aggregate():
    from app.services.audit.review_pipeline import WindowReviewer

    checkpoint = MemoryCheckpoint()
    adapter = FakeAdapter([
        _response(finish_reason="length"),
        _response(),
        _response(),
    ])
    request = _request()

    result = WindowReviewer(adapter, checkpoint=checkpoint).review(request)

    assert result.complete is True
    assert len(checkpoint.records) == 3
    assert checkpoint.records[0]["validation_status"] == "truncated"
    assert checkpoint.records[0]["error_code"] == "OUTPUT_TRUNCATED"
    assert {saved_request.review_window.depth for saved_request, _ in checkpoint.saved} == {
        0,
        1,
    }
    assert any(saved_request == request for saved_request, _ in checkpoint.saved)
