"""法规来源相对合同审查时点的适用性判定。"""
from datetime import date

import pytest

from app.services.rag.applicability import (
    assess_applicability,
    resolve_legal_as_of,
)
from app.services.rag import retriever


@pytest.mark.parametrize(("effective", "expiry", "as_of", "status", "reason_code"), [
    (
        date(2021, 1, 1),
        None,
        date(2026, 1, 1),
        "applicable",
        "SOURCE_APPLICABLE",
    ),
    (
        date(2027, 1, 1),
        None,
        date(2026, 1, 1),
        "not_yet_effective",
        "SOURCE_NOT_YET_EFFECTIVE",
    ),
    (
        date(2021, 1, 1),
        date(2025, 12, 31),
        date(2026, 1, 1),
        "expired",
        "SOURCE_EXPIRED",
    ),
    (
        date(2021, 1, 1),
        None,
        None,
        "unknown_as_of",
        "AS_OF_DATE_UNKNOWN",
    ),
])
def test_assess_applicability(
    effective,
    expiry,
    as_of,
    status,
    reason_code,
):
    result = assess_applicability(effective, expiry, as_of)

    assert result.status == status
    assert result.reason_code == reason_code


def test_filter_docs_keeps_dated_source_when_as_of_is_unknown():
    expired_relative_to_today = (
        1,
        "旧法规正文",
        "旧法规",
        "",
        "law",
        "第一条",
        "2020",
        date(2020, 1, 1),
        date(2020, 12, 31),
        "[]",
        "[]",
        None,
        None,
        "global",
    )

    result = retriever._filter_docs([expired_relative_to_today], as_of=None)

    assert result == [expired_relative_to_today]


def test_retrieval_result_records_unknown_applicability_without_as_of():
    doc = (
        1,
        "法规正文",
        "法规来源",
        "",
        "law",
        "第一条",
        "2021",
        date(2021, 1, 1),
        None,
        "[]",
        "[]",
        None,
        None,
        "global",
    )

    result = retriever._result_from_doc(
        doc,
        score=1.0,
        retrieval_mode="exact",
        as_of=None,
    )

    assert result["applicability_status"] == "unknown_as_of"
    assert result["applicability_reason_code"] == "AS_OF_DATE_UNKNOWN"


@pytest.mark.parametrize(("elements", "expected_date", "expected_source"), [
    (
        {"sign_date": "2026-01-15", "sign_date_confirmed": True},
        date(2026, 1, 15),
        "confirmed_sign_date",
    ),
    (
        {"sign_date": "2026年1月15日", "sign_date_confirmed": True},
        date(2026, 1, 15),
        "confirmed_sign_date",
    ),
    (
        {"sign_date": "2026-01-15"},
        None,
        "unknown",
    ),
    (
        {"sign_date": "日期待定", "sign_date_confirmed": True},
        None,
        "invalid_confirmed_sign_date",
    ),
])
def test_resolve_legal_as_of_requires_confirmed_valid_sign_date(
    elements,
    expected_date,
    expected_source,
):
    context = resolve_legal_as_of(elements)

    assert context.as_of == expected_date
    assert context.source == expected_source
