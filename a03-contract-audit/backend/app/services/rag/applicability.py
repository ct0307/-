"""法规来源相对审查时点的确定性适用性判定。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
from typing import Literal, Mapping


ApplicabilityStatus = Literal[
    "applicable",
    "not_yet_effective",
    "expired",
    "unknown_as_of",
]


@dataclass(frozen=True)
class ApplicabilityResult:
    status: ApplicabilityStatus
    reason_code: str


@dataclass(frozen=True)
class LegalAsOfContext:
    as_of: date | None
    source: Literal[
        "confirmed_sign_date",
        "invalid_confirmed_sign_date",
        "unknown",
    ]


def assess_applicability(
    effective: date | None,
    expiry: date | None,
    as_of: date | None,
) -> ApplicabilityResult:
    if as_of is None:
        return ApplicabilityResult("unknown_as_of", "AS_OF_DATE_UNKNOWN")
    if effective is not None and effective > as_of:
        return ApplicabilityResult(
            "not_yet_effective",
            "SOURCE_NOT_YET_EFFECTIVE",
        )
    if expiry is not None and expiry < as_of:
        return ApplicabilityResult("expired", "SOURCE_EXPIRED")
    return ApplicabilityResult("applicable", "SOURCE_APPLICABLE")


def resolve_legal_as_of(elements: Mapping[str, object]) -> LegalAsOfContext:
    """只接受显式确认的合同签订日期，拒绝未核验的自动抽取值。"""
    if elements.get("sign_date_confirmed") is not True:
        return LegalAsOfContext(None, "unknown")
    raw = str(elements.get("sign_date", "")).strip()
    matched = re.fullmatch(
        r"(\d{4})\s*(?:-|/|年)\s*(\d{1,2})\s*(?:-|/|月)\s*(\d{1,2})\s*日?",
        raw,
    )
    if matched is None:
        return LegalAsOfContext(None, "invalid_confirmed_sign_date")
    try:
        parsed = date(*(int(value) for value in matched.groups()))
    except ValueError:
        return LegalAsOfContext(None, "invalid_confirmed_sign_date")
    return LegalAsOfContext(parsed, "confirmed_sign_date")
