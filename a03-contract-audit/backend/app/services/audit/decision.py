"""集中发布风险结论，避免不同审查路径产生不一致状态。"""

from dataclasses import dataclass
from typing import Literal, Sequence


DecisionStatus = Literal["accepted", "manual_review", "rejected"]


@dataclass(frozen=True)
class RiskDecision:
    status: DecisionStatus
    reason_codes: tuple[str, ...]


def decide_risk(
    *,
    original_verified: bool | None,
    support_status: str,
    has_conflict: bool,
    rule_statuses: Sequence[str] = (),
    parse_quality_ok: bool = True,
    secondary_status: str = "not_required",
) -> RiskDecision:
    reasons: list[str] = []
    if original_verified is not True:
        reasons.append("ORIGINAL_TEXT_UNRESOLVED")
    if not parse_quality_ok:
        reasons.append("PARSE_QUALITY_LOW")
    if has_conflict:
        reasons.append("UNRESOLVED_CONFLICT")
    if secondary_status in {"conflict", "manual_required", "pending"}:
        reasons.append("SECONDARY_REVIEW_PENDING")
    if any(status in {"unclear", "error"} for status in rule_statuses):
        reasons.append("RULE_RESULT_UNRESOLVED")
    if reasons:
        return RiskDecision("manual_review", tuple(reasons))
    if support_status == "contradicted":
        return RiskDecision("rejected", ("EVIDENCE_CONTRADICTS_CLAIM",))
    if support_status != "supported":
        return RiskDecision("manual_review", ("EVIDENCE_UNRESOLVED",))
    return RiskDecision("accepted", ("ALL_GATES_PASSED",))


def apply_risk_decision(risk: dict, decision: RiskDecision) -> dict:
    """Map the pure decision to legacy publication fields."""
    updated = dict(risk)
    updated["decision_status"] = decision.status
    updated["decision_reason_codes"] = list(decision.reason_codes)
    updated["claim_status"] = decision.status
    updated["requires_manual_review"] = decision.status == "manual_review"
    updated["decision_trace"] = {
        "status": decision.status,
        "reason_codes": list(decision.reason_codes),
    }
    if decision.status == "rejected":
        updated["claim_status"] = "rejected"
    return updated
