"""预算耗尽保留准确原因，不重试、不丢弃已验证候选。"""
import json
from dataclasses import replace

import pytest

from app.core.config import settings
from app.llm.base import LLMResponse
from app.services.audit.failure import audit_failure
from app.services.audit.result_quality import AuditCoverage, decide_audit_status
from app.services.audit.review_pipeline import (
    BufferedWindowCheckpoint,
    ReviewWindow,
    WindowReviewer,
    WindowReviewRequest,
)
from app.services.audit.workflow import AuditBudget, BudgetAdapter
from app.services.rag.contract_structure import ContractWindow


class ReplayAdapter:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0

    def chat(self, system, user, *, temperature=0.2, options=None):
        self.calls += 1
        return LLMResponse(json.dumps(next(self.responses), ensure_ascii=False), "test")


def _request(*, two_stage=False):
    request = WindowReviewRequest(
        contract_id=1,
        audit_job_id=1,
        audit_generation=1,
        agent="legal",
        dimensions=("payment",),
        review_window=ReviewWindow(ContractWindow("budget-window", ("第一条",), "验收后付款。")),
        system_prompt="仅输出审查 JSON",
        build_user_prompt=lambda *_args: "合成条款",
    )
    if two_stage:
        request = replace(
            request,
            discovery_system_prompt="发现风险",
            build_discovery_prompt=lambda *_args: "合成候选",
            enrichment_system_prompt="补充风险",
            build_enrichment_prompt=lambda *_args: "补充合成候选",
        )
    return request


FINDING = {"level": "high", "category": "付款风险", "quote": "验收后付款。"}
ENRICHMENT = {"reason": "付款期限缺少明确约定。", "suggestion": "补充明确的付款期限。"}


@pytest.mark.parametrize("two_stage,responses,max_calls,retained", [
    (False, [{"risks": [FINDING | ENRICHMENT], "has_more": True}], 1, 1),
    (True, [{"risks": [FINDING], "has_more": False}], 1, 0),
    (True, [{"risks": [FINDING, FINDING | {"category": "履约风险"}], "has_more": False}, ENRICHMENT], 2, 1),
    (True, [{"risks": [FINDING], "has_more": True}, ENRICHMENT], 2, 1),
])
def test_exhausted_budget_keeps_code_and_partial_results_without_retry_or_valid_checkpoint(
    monkeypatch, two_stage, responses, max_calls, retained,
):
    monkeypatch.setattr(settings, "AUDIT_BATCH_ENRICHMENT_ENABLED", False)
    adapter = ReplayAdapter(responses)
    budget = AuditBudget(max_calls=max_calls, max_tokens=100000)
    checkpoint = BufferedWindowCheckpoint()
    waits = []
    result = WindowReviewer(
        BudgetAdapter(adapter, budget), checkpoint=checkpoint, sleep=waits.append,
    ).review(_request(two_stage=two_stage))

    assert [issue.code for issue in result.issues] == ["AUDIT_BUDGET_EXHAUSTED"]
    assert "预算已用尽" in result.issues[0].detail
    assert "未启动新的模型调用" in result.issues[0].detail
    assert result.complete is False
    assert result.completed_windows == 0
    assert len(result.candidates) == retained
    if retained:
        assert result.candidates[0].quote == FINDING["quote"]
        assert result.candidates[0].reason == ENRICHMENT["reason"]
    assert adapter.calls == max_calls
    assert budget.calls == max_calls
    assert waits == []
    execution = checkpoint.execution(result)
    assert execution.saved_results == ()
    assert execution.observations[-1].error_code == "AUDIT_BUDGET_EXHAUSTED"
    decision = decide_audit_status([], result.issues, AuditCoverage(1, 0))
    assert decision.status != "done"
    assert "AUDIT_BUDGET_EXHAUSTED" in decision.reasons


@pytest.mark.parametrize("two_stage", [False, True])
@pytest.mark.parametrize("max_calls,max_tokens", [(0, 100000), (10, 0)])
def test_empty_call_or_token_budget_never_starts_a_model_request(two_stage, max_calls, max_tokens):
    adapter = ReplayAdapter([])
    budget = AuditBudget(max_calls=max_calls, max_tokens=max_tokens)
    checkpoint = BufferedWindowCheckpoint()
    result = WindowReviewer(BudgetAdapter(adapter, budget), checkpoint=checkpoint).review(
        _request(two_stage=two_stage)
    )

    assert [issue.code for issue in result.issues] == ["AUDIT_BUDGET_EXHAUSTED"]
    assert adapter.calls == budget.calls == 0
    assert result.complete is False
    assert result.candidates == []
    assert checkpoint.execution(result).saved_results == ()


@pytest.mark.parametrize("snapshot,explicit", [
    ({}, "AUDIT_BUDGET_EXHAUSTED"),
    ({"issues": [{"code": "AUDIT_BUDGET_EXHAUSTED"}]}, None),
    ({"quality_reasons": ["INCOMPLETE_COVERAGE", "MODEL_TIMEOUT", "AUDIT_BUDGET_EXHAUSTED"]}, None),
])
def test_budget_failure_is_actionable_and_never_automatically_retryable(snapshot, explicit):
    failure = audit_failure({
        "status": "failed",
        "error_code": explicit,
        "error": "供应商敏感原文",
        "result_json": json.dumps(snapshot),
    })

    assert failure.code == "AUDIT_BUDGET_EXHAUSTED"
    assert "预算已用尽" in failure.message
    assert "人工复核" in failure.message
    assert failure.retryable is False
    assert "预算" in failure.action
    assert "敏感原文" not in repr(failure)
