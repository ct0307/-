import pytest

from app.services.audit.decision import decide_risk


@pytest.mark.parametrize(("original", "support", "conflict", "decision"), [
    (True, "supported", False, "accepted"),
    (False, "supported", False, "manual_review"),
    (True, "unclear", False, "manual_review"),
    (True, "contradicted", False, "rejected"),
    (True, "supported", True, "manual_review"),
])
def test_decide_risk(original, support, conflict, decision):
    assert decide_risk(
        original_verified=original,
        support_status=support,
        has_conflict=conflict,
    ).status == decision


def test_unresolved_rule_result_requires_manual_review():
    result = decide_risk(
        original_verified=True,
        support_status="supported",
        has_conflict=False,
        rule_statuses=("unclear",),
    )
    assert result.status == "manual_review"
    assert "RULE_RESULT_UNRESOLVED" in result.reason_codes
