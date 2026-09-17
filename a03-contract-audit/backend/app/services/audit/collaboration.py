"""双 Agent 独立首审与白名单结构化交接。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, Iterable, Mapping, TypeVar

from app.services.audit.agent_profiles import AgentRole


ResultT = TypeVar("ResultT")


@dataclass(frozen=True)
class FirstPassBundle(Generic[ResultT]):
    legal: ResultT | None = None
    finance: ResultT | None = None

    def items(self) -> tuple[tuple[AgentRole, ResultT], ...]:
        values: list[tuple[AgentRole, ResultT]] = []
        if self.legal is not None:
            values.append(("legal", self.legal))
        if self.finance is not None:
            values.append(("finance", self.finance))
        return tuple(values)


def first_pass(
    run_agent: Callable[[AgentRole], ResultT],
    *,
    roles: Iterable[AgentRole],
) -> FirstPassBundle[ResultT]:
    """顺序执行相互不可见的首审；并行化留给独立性能阶段。"""
    results = {role: run_agent(role) for role in roles}
    return FirstPassBundle(
        legal=results.get("legal"),
        finance=results.get("finance"),
    )


@dataclass(frozen=True)
class ReviewHandoff:
    from_agent: AgentRole
    to_agent: AgentRole
    claim_ids: tuple[str, ...]
    categories: tuple[str, ...]
    clause_ids: tuple[tuple[str, ...], ...]
    payment_status: str
    payment_total_percentage: str | None
    payment_clause_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]

    def to_payload(self) -> dict[str, object]:
        """只序列化允许跨 Agent 传递的确定性字段。"""
        return {
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "claim_ids": list(self.claim_ids),
            "categories": list(self.categories),
            "clause_ids": [list(values) for values in self.clause_ids],
            "deterministic_facts": {
                "payment_status": self.payment_status,
                "payment_total_percentage": self.payment_total_percentage,
                "payment_clause_ids": list(self.payment_clause_ids),
            },
            "reason_codes": list(self.reason_codes),
        }


def build_review_handoff(
    *,
    from_agent: AgentRole,
    to_agent: AgentRole,
    risks: Iterable[Mapping[str, object]],
    payment_schedule: Mapping[str, object],
) -> ReviewHandoff:
    """从已完成首审的结果构造受控交接，不传递自由推理文本。"""
    claims = [risk for risk in risks if str(risk.get("claim_id", ""))]
    reason_codes = sorted({
        _handoff_reason_code(str(risk.get("category", "")))
        for risk in claims
    })
    return ReviewHandoff(
        from_agent=from_agent,
        to_agent=to_agent,
        claim_ids=tuple(str(risk["claim_id"]) for risk in claims),
        categories=tuple(str(risk.get("category", "")) for risk in claims),
        clause_ids=tuple(
            tuple(str(value) for value in risk.get("source_clause_ids", ()) or ())
            for risk in claims
        ),
        payment_status=str(payment_schedule.get("status", "unknown")),
        payment_total_percentage=(
            str(payment_schedule["total_percentage"])
            if payment_schedule.get("total_percentage") is not None
            else None
        ),
        payment_clause_ids=tuple(
            str(value) for value in payment_schedule.get("clause_ids", ()) or ()
        ),
        reason_codes=tuple(reason_codes),
    )


def _handoff_reason_code(category: str) -> str:
    if "关联" in category:
        return "RELATED_PARTY_REVIEW"
    if "收款" in category or "账户" in category:
        return "PAYEE_IDENTITY_REVIEW"
    if "付款" in category or "金额" in category or "发票" in category:
        return "PAYMENT_REVIEW"
    return "CROSS_DOMAIN_REVIEW"

