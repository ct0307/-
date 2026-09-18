"""合同原文完整性和绝对免责规则。"""
from __future__ import annotations

import re
import unicodedata

from app.services.audit.rules.schema import HandlerOutcome, RuleDefinition


_BLANK = r"(?:\s|[_＿]){2,}"
_PATTERNS = {
    "party_missing": re.compile(
        r"(?:乙方(?:(?:（[^）]{0,20}）)|(?:\([^)]{0,20}\)))?|身份证号码)"
        r"\s*[：:]\s*$"
    ),
    "work_scope_missing": re.compile(rf"甲方将{_BLANK}项目"),
    "payment_terms_missing": re.compile(
        rf"每月{_BLANK}日前以{_BLANK}方式(?:支付|结算)"
    ),
    "absolute_injury_waiver": re.compile(
        r"(?:不承担.*(?:工伤|意外伤害).*(?:任何|全部).*责任|"
        r"人身损害.*一切后果.*自行承担)"
    ),
}
_REASON_CODES = {
    "party_missing": "CONTRACT_PARTY_MISSING",
    "work_scope_missing": "WORK_SCOPE_MISSING",
    "payment_terms_missing": "PAYMENT_TERMS_MISSING",
    "absolute_injury_waiver": "ABSOLUTE_INJURY_WAIVER",
}


def party_missing(rule: RuleDefinition, facts: dict) -> HandlerOutcome:
    return _match_contract(rule, facts)


def work_scope_missing(rule: RuleDefinition, facts: dict) -> HandlerOutcome:
    return _match_contract(rule, facts)


def payment_terms_missing(rule: RuleDefinition, facts: dict) -> HandlerOutcome:
    return _match_contract(rule, facts)


def absolute_injury_waiver(rule: RuleDefinition, facts: dict) -> HandlerOutcome:
    return _match_contract(rule, facts)


def _match_contract(rule: RuleDefinition, facts: dict) -> HandlerOutcome:
    contract_text = str(facts.get("contract_text") or "")
    if not contract_text:
        return HandlerOutcome(
            status="unclear",
            reason_code="CONTRACT_TEXT_MISSING",
        )
    pattern = _PATTERNS[rule.handler]
    quote = _find_exact_quote(contract_text, pattern)
    if quote is None:
        return HandlerOutcome(
            status="not_hit",
            reason_code=f"{_REASON_CODES[rule.handler]}_NOT_FOUND",
        )
    return HandlerOutcome(
        status="hit",
        clause_ids=[str(value) for value in facts.get("clause_ids", [])],
        facts={"quote": quote},
        reason_code=_REASON_CODES[rule.handler],
    )


def _find_exact_quote(contract_text: str, pattern: re.Pattern[str]) -> str | None:
    lines = [line.strip() for line in contract_text.splitlines() if line.strip()]
    for line in lines:
        if pattern.search(unicodedata.normalize("NFKC", line)):
            return line
    normalized_text, source_indexes = _normalize_with_source_indexes(contract_text)
    match = pattern.search(normalized_text)
    if match is None:
        return None
    source_start = source_indexes[match.start()]
    source_end = source_indexes[match.end() - 1] + 1
    return contract_text[source_start:source_end]


def _normalize_with_source_indexes(text: str) -> tuple[str, list[int]]:
    normalized_parts: list[str] = []
    source_indexes: list[int] = []
    for source_index, character in enumerate(text):
        normalized = unicodedata.normalize("NFKC", character)
        normalized_parts.append(normalized)
        source_indexes.extend([source_index] * len(normalized))
    return "".join(normalized_parts), source_indexes
