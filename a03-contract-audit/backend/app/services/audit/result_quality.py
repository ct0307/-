"""以覆盖率、结构化问题和证据状态决定审查终态。"""
from dataclasses import dataclass
from typing import Literal, Mapping, Sequence

from app.services.audit.protocol import ReviewIssue


AuditTerminalStatus = Literal["done", "review_required", "audit_failed"]


@dataclass(frozen=True)
class AuditCoverage:
    planned: int
    completed: int

    def __post_init__(self) -> None:
        if self.planned < 0 or self.completed < 0 or self.completed > self.planned:
            raise ValueError("窗口覆盖数必须非负，已完成数不能超过计划数")

    @property
    def complete(self) -> bool:
        return self.planned > 0 and self.completed == self.planned


@dataclass(frozen=True)
class AuditQualityDecision:
    status: AuditTerminalStatus
    requires_review: bool
    reasons: tuple[str, ...]


def decide_audit_status(
    risks: Sequence[Mapping],
    issues: Sequence[ReviewIssue | Mapping],
    coverage: AuditCoverage,
) -> AuditQualityDecision:
    """仅机器码参与判定；问题顺序与描述文本均不影响终态。"""
    reasons: list[str] = []
    if not coverage.complete:
        reasons.append("INCOMPLETE_COVERAGE")
    reasons.extend(sorted({
        issue.code if isinstance(issue, ReviewIssue) else issue["code"]
        for issue in issues
    }))
    if any(risk.get("original_text_verified") is not True for risk in risks):
        reasons.append("ORIGINAL_TEXT_UNRESOLVED")
    if any(
        risk.get("evidence_status") != "supported"
        or risk.get("support_relation_status") != "supported"
        for risk in risks
    ):
        reasons.append("EVIDENCE_UNRESOLVED")
    if any(
        risk.get("secondary_review_status", "not_required")
        in {"pending", "conflict", "manual_required"}
        for risk in risks
    ):
        reasons.append("SECONDARY_REVIEW_PENDING")
    unique_reasons = tuple(dict.fromkeys(reasons))
    if not unique_reasons:
        return AuditQualityDecision("done", False, ())
    usable = any(risk.get("original_text_verified") is True for risk in risks)
    status: AuditTerminalStatus = (
        "audit_failed"
        if coverage.planned == 0 or (coverage.completed == 0 and not usable)
        else "review_required"
    )
    return AuditQualityDecision(status, status == "review_required", unique_reasons)
