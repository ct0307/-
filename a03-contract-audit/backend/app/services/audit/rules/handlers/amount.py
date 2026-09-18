"""金额归一化与一致性规则。"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from app.services.audit.rules.schema import HandlerOutcome, RuleDefinition


_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "壹": 1,
    "贰": 2,
    "叁": 3,
    "肆": 4,
    "伍": 5,
    "陆": 6,
    "柒": 7,
    "捌": 8,
    "玖": 9,
}
_UNITS = {
    "十": 10,
    "百": 100,
    "千": 1000,
    "拾": 10,
    "佰": 100,
    "仟": 1000,
    "万": 10000,
    "亿": 100000000,
}


def amount_consistency(_rule: RuleDefinition, facts: dict) -> HandlerOutcome:
    raw_amounts = facts.get("amounts")
    if not isinstance(raw_amounts, (list, tuple)) or not raw_amounts:
        return HandlerOutcome(status="unclear", reason_code="AMOUNT_MISSING")
    normalized: list[Decimal] = []
    clause_ids: list[str] = []
    for item in raw_amounts:
        if not isinstance(item, dict):
            return HandlerOutcome(status="unclear", reason_code="AMOUNT_UNCLEAR")
        value = _parse_amount(item.get("value"), item.get("unit"))
        if value is None:
            return HandlerOutcome(status="unclear", reason_code="AMOUNT_UNCLEAR")
        normalized.append(value)
        if item.get("clause_id") is not None:
            clause_ids.append(str(item["clause_id"]))
    rendered = [_decimal_text(value) for value in normalized]
    if len(set(normalized)) > 1:
        return HandlerOutcome(
            status="hit",
            clause_ids=clause_ids,
            facts={"normalized_amounts": rendered},
            calculation="; ".join(rendered),
            reason_code="AMOUNT_VALUES_MISMATCH",
        )
    return HandlerOutcome(
        status="not_hit",
        clause_ids=clause_ids,
        facts={"normalized_amounts": rendered},
        calculation="; ".join(rendered),
        reason_code="AMOUNT_VALUES_CONSISTENT",
    )


def _parse_amount(raw: object, unit: object) -> Decimal | None:
    if raw is None:
        return None
    text = str(raw).strip().replace(",", "").replace("，", "")
    if not text:
        return None
    multiplier = Decimal("1")
    unit_text = str(unit or "").strip()
    if unit_text in {"万元", "万", "W"}:
        multiplier = Decimal("10000")
    elif unit_text not in {"", "元", "人民币", "RMB", "CNY"}:
        return None
    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text):
        try:
            return Decimal(text) * multiplier
        except InvalidOperation:
            return None
    return _parse_uppercase(text)


def _parse_uppercase(text: str) -> Decimal | None:
    text = re.sub(r"^(人民币|人民币大写)", "", text)
    text = text.rstrip("整圆元")
    if not text:
        return None
    total = Decimal("0")
    section = Decimal("0")
    digit: int | None = None
    for char in text:
        if char in _DIGITS:
            digit = _DIGITS[char]
        elif char in _UNITS:
            unit = _UNITS[char]
            if unit < 10000:
                if digit is None:
                    digit = 1
                section += Decimal(digit) * unit
                digit = None
            else:
                section += Decimal(digit or 0)
                total += section * unit
                section = Decimal("0")
                digit = None
        elif char in {"角", "分"}:
            # 金额规则当前以元为最小审计单位，带角分时保留小数。
            if digit is not None:
                section += Decimal(digit) / (Decimal("10") if char == "角" else Decimal("100"))
                digit = None
        else:
            return None
    if digit is not None:
        section += Decimal(digit)
    return total + section


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")
