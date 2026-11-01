"""付款数值规则。"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.services.audit.rules.schema import HandlerOutcome, RuleDefinition


def payment_total(_rule: RuleDefinition, facts: dict) -> HandlerOutcome:
    events = facts.get("payment_events")
    if isinstance(events, (list, tuple)) and events:
        if any(not isinstance(item, dict) or item.get("conditional") for item in events):
            return HandlerOutcome(status="unclear", reason_code="PAYMENT_CONDITIONAL_UNCLEAR")
        bases = {str(item.get("base") or "").strip() for item in events}
        if not bases or "" in bases or len(bases) != 1:
            return HandlerOutcome(status="unclear", reason_code="PAYMENT_BASE_UNCLEAR")
        raw_values = [item.get("percentage") for item in events]
    else:
        raw_values = facts.get("payment_percentages")
    if not isinstance(raw_values, (list, tuple)) or not raw_values:
        return HandlerOutcome(
            status="unclear",
            reason_code="PAYMENT_PERCENTAGES_MISSING",
        )
    try:
        values = [Decimal(str(value)) for value in raw_values]
    except (InvalidOperation, ValueError):
        return HandlerOutcome(
            status="unclear",
            reason_code="PAYMENT_PERCENTAGES_INVALID",
        )
    total = sum(values, Decimal("0"))
    rendered = [_decimal_text(value) for value in values]
    total_text = _decimal_text(total)
    if total > Decimal("100"):
        status = "hit"
        reason_code = "PAYMENT_TOTAL_EXCEEDS_100"
    elif total == Decimal("100"):
        status = "not_hit"
        reason_code = "PAYMENT_TOTAL_EQUALS_100"
    else:
        status = "unclear"
        reason_code = "PAYMENT_TOTAL_BELOW_100"
    return HandlerOutcome(
        status=status,
        clause_ids=[str(value) for value in facts.get("clause_ids", [])],
        facts={"percentages": rendered, "total": total_text},
        calculation=f"{' + '.join(rendered)} = {total_text}",
        reason_code=reason_code,
    )


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")
