"""规则 Handler 的统一、保守执行入口。"""
from __future__ import annotations

from collections.abc import Callable

from app.core.logging import get_logger
from app.services.audit.rules.handlers.completeness import (
    absolute_injury_waiver,
    party_missing,
    payment_terms_missing,
    work_scope_missing,
)
from app.services.audit.rules.handlers.payment import payment_total
from app.services.audit.rules.handlers.amount import amount_consistency
from app.services.audit.rules.handlers.cross_clause import (
    date_order,
    payee_consistency,
    payment_deadline_conflict,
)
from app.services.audit.rules.schema import (
    HandlerOutcome,
    RuleDefinition,
    RuleResult,
)


log = get_logger("audit.rules")
RuleHandler = Callable[[RuleDefinition, dict], HandlerOutcome]

HANDLERS: dict[str, RuleHandler] = {
    "party_missing": party_missing,
    "work_scope_missing": work_scope_missing,
    "payment_terms_missing": payment_terms_missing,
    "absolute_injury_waiver": absolute_injury_waiver,
    "payment_total": payment_total,
    "amount_consistency": amount_consistency,
    "payee_consistency": payee_consistency,
    "date_order": date_order,
    "payment_deadline_conflict": payment_deadline_conflict,
}


def execute_rule(rule: RuleDefinition, facts: dict) -> RuleResult:
    try:
        outcome = HANDLERS[rule.handler](rule, facts)
    except Exception as exc:
        log.warning(
            "audit.rule_execution_failed",
            rule_id=rule.rule_id,
            error_type=type(exc).__name__,
        )
        return RuleResult(
            rule_id=rule.rule_id,
            rule_version=rule.version,
            status="error",
            severity=rule.severity,
            reason_code="RULE_EXECUTION_FAILED",
        )
    return RuleResult(
        rule_id=rule.rule_id,
        rule_version=rule.version,
        status=outcome.status,
        severity=rule.severity,
        clause_ids=outcome.clause_ids,
        facts=outcome.facts,
        calculation=outcome.calculation,
        reason_code=outcome.reason_code,
    )
