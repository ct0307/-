"""跨条款主体、日期和付款期限一致性规则。"""
from __future__ import annotations

import re
from datetime import date

from app.services.audit.rules.schema import HandlerOutcome, RuleDefinition


def payee_consistency(_rule: RuleDefinition, facts: dict) -> HandlerOutcome:
    payees = facts.get("payees")
    if not isinstance(payees, (list, tuple)) or not payees:
        return HandlerOutcome(status="unclear", reason_code="PAYEE_MISSING")
    identities: list[tuple[str, str]] = []
    for item in payees:
        if not isinstance(item, dict):
            return HandlerOutcome(status="unclear", reason_code="PAYEE_IDENTITY_UNCLEAR")
        name = _normalize_name(item.get("name"))
        credit_code = str(item.get("credit_code") or "").strip().upper()
        if not name or not credit_code:
            return HandlerOutcome(status="unclear", reason_code="PAYEE_IDENTITY_UNCLEAR")
        identities.append((name, credit_code))
    if len(set(identities)) > 1:
        return HandlerOutcome(status="hit", reason_code="PAYEE_IDENTITY_MISMATCH")
    return HandlerOutcome(status="not_hit", reason_code="PAYEE_IDENTITY_CONSISTENT")


def date_order(_rule: RuleDefinition, facts: dict) -> HandlerOutcome:
    signing = _parse_date(facts.get("signing_date"))
    performance = _parse_date(facts.get("performance_date"))
    if signing is None or performance is None:
        return HandlerOutcome(status="unclear", reason_code="DATE_INCOMPLETE")
    if performance < signing:
        return HandlerOutcome(
            status="hit",
            facts={"signing_date": signing.isoformat(), "performance_date": performance.isoformat()},
            calculation=f"{performance.isoformat()} < {signing.isoformat()}",
            reason_code="PERFORMANCE_BEFORE_SIGNING",
        )
    return HandlerOutcome(status="not_hit", reason_code="DATE_ORDER_VALID")


def payment_deadline_conflict(_rule: RuleDefinition, facts: dict) -> HandlerOutcome:
    deadlines = facts.get("payment_deadlines")
    if not isinstance(deadlines, (list, tuple)) or not deadlines:
        return HandlerOutcome(status="unclear", reason_code="PAYMENT_DEADLINE_MISSING")
    grouped: dict[str, list[dict]] = {}
    for item in deadlines:
        if not isinstance(item, dict) or not str(item.get("trigger") or "").strip():
            return HandlerOutcome(status="unclear", reason_code="PAYMENT_DEADLINE_UNCLEAR")
        grouped.setdefault(_normalize_name(item["trigger"]), []).append(item)
    for entries in grouped.values():
        parsed = [(entry, _parse_days(entry.get("deadline"))) for entry in entries]
        if any(days is None for _, days in parsed):
            return HandlerOutcome(status="unclear", reason_code="PAYMENT_DEADLINE_UNCLEAR")
        for index, (left, left_days) in enumerate(parsed):
            for right, right_days in parsed[index + 1 :]:
                if left_days != right_days:
                    clause_ids = [str(left["clause_id"]), str(right["clause_id"])] if left.get("clause_id") and right.get("clause_id") else []
                    return HandlerOutcome(status="hit", clause_ids=clause_ids, reason_code="PAYMENT_DEADLINE_CONFLICT")
    return HandlerOutcome(status="not_hit", reason_code="PAYMENT_DEADLINES_CONSISTENT")


def _normalize_name(value: object) -> str:
    return "".join(str(value or "").split()).replace("﹒", ".")


def _parse_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _parse_days(value: object) -> int | None:
    match = re.fullmatch(r"\s*(\d+)\s*(?:日|天)\s*", str(value or ""))
    return int(match.group(1)) if match else None
