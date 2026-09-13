"""正式审查结果的统一终态质量门禁。"""
from dataclasses import FrozenInstanceError

import pytest


def _quality():
    from app.services.audit.result_quality import AuditCoverage, decide_audit_status
    return AuditCoverage, decide_audit_status


def _risk(**changes):
    return dict(original_text_verified=True, evidence_status="supported",
                support_relation_status="supported", **changes)


def test_complete_zero_risks_is_done():
    coverage, decide = _quality()
    decision = decide([], [], coverage(2, 2))
    assert (decision.status, decision.requires_review, decision.reasons) == ("done", False, ())


def test_empty_plan_and_no_completed_work_fail():
    coverage, decide = _quality()
    assert decide([], [], coverage(0, 0)).status == "audit_failed"
    assert decide([], [], coverage(0, 0)).reasons == ("INCOMPLETE_COVERAGE",)
    assert decide([_risk()], [], coverage(0, 0)).status == "audit_failed"
    decision = decide([], [{"code": "OUTPUT_TRUNCATED"}], coverage(2, 0))
    assert decision.status == "audit_failed"
    assert decision.reasons == ("INCOMPLETE_COVERAGE", "OUTPUT_TRUNCATED")


@pytest.mark.parametrize("planned,completed,risks,issues,status,requires_review", [
    (0, 0, [], [], "audit_failed", False),
    (0, 0, [_risk()], [], "audit_failed", False),
    (2, 0, [], [{"code": "OUTPUT_TRUNCATED"}], "audit_failed", False),
    (2, 0, [{**_risk(), "original_text_verified": False}], [], "audit_failed", False),
    (2, 1, [], [], "review_required", True),
    (2, 0, [_risk()], [], "review_required", True),
    (2, 2, [], [], "done", False),
])
def test_review_flag_is_only_true_for_review_required(
    planned, completed, risks, issues, status, requires_review,
):
    coverage, decide = _quality()
    decision = decide(risks, issues, coverage(planned, completed))
    assert decision.status == status
    assert decision.requires_review is requires_review


def test_partial_results_and_partial_coverage_require_review():
    coverage, decide = _quality()
    assert decide([_risk()], [{"code": "OUTPUT_TRUNCATED"}], coverage(2, 0)).status == "review_required"
    assert decide([], [], coverage(2, 1)).status == "review_required"
    unresolved = {**_risk(), "original_text_verified": False}
    assert decide([unresolved], [], coverage(2, 0)).status == "audit_failed"


@pytest.mark.parametrize("field,value,reason", [
    ("original_text_verified", False, "ORIGINAL_TEXT_UNRESOLVED"),
    ("original_text_verified", None, "ORIGINAL_TEXT_UNRESOLVED"),
    ("evidence_status", "partially_supported", "EVIDENCE_UNRESOLVED"),
    ("support_relation_status", "unclear", "EVIDENCE_UNRESOLVED"),
    ("secondary_review_status", "pending", "SECONDARY_REVIEW_PENDING"),
    ("secondary_review_status", "conflict", "SECONDARY_REVIEW_PENDING"),
    ("secondary_review_status", "manual_required", "SECONDARY_REVIEW_PENDING"),
])
def test_done_requires_verified_quote_evidence_and_secondary_review(field, value, reason):
    coverage, decide = _quality()
    decision = decide([{**_risk(), field: value}], [], coverage(1, 1))
    assert decision.status == "review_required"
    assert decision.requires_review is True
    assert decision.reasons == (reason,)


def test_reasons_are_deduplicated_and_independent_of_issue_order():
    coverage, decide = _quality()
    issues = [{"code": "OUTPUT_TRUNCATED", "detail": "随机自由文本"},
              {"code": "INVALID_MODEL_OUTPUT"}, {"code": "OUTPUT_TRUNCATED"}]
    expected = ("INCOMPLETE_COVERAGE", "INVALID_MODEL_OUTPUT", "OUTPUT_TRUNCATED")
    assert decide([], issues, coverage(2, 1)).reasons == expected
    assert decide([], list(reversed(issues)), coverage(2, 1)).reasons == expected


def test_coverage_is_frozen_and_validated():
    coverage, _ = _quality()
    with pytest.raises(FrozenInstanceError):
        coverage(1, 1).completed = 0
    for planned, completed in [(-1, 0), (1, -1), (1, 2)]:
        with pytest.raises(ValueError):
            coverage(planned, completed)
    assert coverage(0, 0).complete is False
    assert coverage(2, 2).complete is True
