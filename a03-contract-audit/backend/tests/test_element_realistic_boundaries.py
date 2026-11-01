from types import SimpleNamespace

import pytest

from app.services.parser.elements import extract_element_result
from app.services.parser.extractor import DocumentBlock, DocumentParseResult, SourceAnchor


def _parsed(text: str):
    return SimpleNamespace(text=text, blocks=[], total_pages=1, missing_pages=[])


def test_total_price_wins_over_deposit_and_unit_price():
    result = extract_element_result(_parsed("合同总价为人民币100万元，履约保证金为10万元，单价为20元/件。"))

    assert result.values["amount"] == "人民币100万元"
    assert "amount" not in result.review_fields
    assert result.evidence["amount"].validation == "valid"


def test_framework_contract_without_fixed_total_does_not_invent_amount():
    result = extract_element_result(_parsed("本框架合同有效期两年，具体订单据实结算，不设固定总额。"))

    assert result.values["amount"] is None
    assert result.values["duration"] == "两年"


def test_extracts_start_end_dates_relative_term_and_cross_clause_term():
    result = extract_element_result(
        _parsed(
            "服务期限自2026年1月1日起至2027年1月1日止；验收后30日内付款；"
            "服务期见第3条至第5条。"
        )
    )

    assert result.values["duration"] == "自2026年1月1日起至2027年1月1日止"
    assert any("30日内" in item for item in result.values["payment_terms"])


@pytest.mark.parametrize("weak_clause", [
    "履约保证金的总金额为10万元，单价为20元/件",
    "分项服务费为20万元，设备清单总金额为30万元",
])
def test_strong_contract_total_is_not_conflicted_by_weaker_money(weak_clause):
    result = extract_element_result(_parsed(f"合同总价100万元。{weak_clause}。"))

    assert result.values["amount"] == "100万元"
    assert "amount" not in result.review_fields
    assert result.evidence["amount"].validation == "valid"


@pytest.mark.parametrize("weak_clause", [
    "暂估采购额为100万元",
    "总金额为100万元",
    "服务费为100万元",
])
def test_unstructured_framework_without_fixed_total_suppresses_weak_money(weak_clause):
    result = extract_element_result(_parsed(
        f"本框架协议不设固定总额，以实际订单据实结算。{weak_clause}，仅供预算参考。"
    ))

    assert result.values["amount"] is None
    assert "amount" not in result.evidence


def test_framework_without_fixed_total_wording_does_not_use_budget_fee():
    result = extract_element_result(_parsed("本框架合同无固定总额，预算服务费为10万元。"))

    assert result.values["amount"] is None
    assert "amount" not in result.evidence
    assert "amount" not in result.review_fields


def test_structured_framework_without_fixed_total_has_no_amount():
    result = extract_element_result(_parsed(
        "合同金额或结算口径为无固定总额。付款按“按月据实结算”执行。"
    ))

    assert result.values["amount"] is None
    assert "amount" not in result.evidence


@pytest.mark.parametrize("prefix", [
    "本框架合同不设固定总额。",
    "合同总价为100万元。",
])
def test_generic_structured_amount_does_not_promote_guarantee_money(prefix):
    result = extract_element_result(_parsed(
        prefix + "履约保证金金额为10万元；付款节点为签订后支付。"
    ))

    if "合同总价" in prefix:
        assert result.values["amount"] == "100万元"
        assert result.evidence["amount"].validation == "valid"
    else:
        assert result.values["amount"] is None
        assert "amount" not in result.evidence
    assert "amount" not in result.review_fields


def test_generic_structured_budget_does_not_override_no_fixed_total():
    result = extract_element_result(_parsed(
        "本框架合同不设固定总额。预算金额为10万元；付款节点为签订后支付。"
    ))

    assert result.values["amount"] is None
    assert "amount" not in result.evidence


def test_fixed_independent_order_still_uses_its_structured_total():
    result = extract_element_result(_parsed(
        "本框架合同不设固定总额。"
        "本订单采用固定计价，金额为人民币42万元；付款节点为验收后付款。"
    ))

    assert result.values["amount"] == "人民币42万元"
    assert "amount" not in result.review_fields


def test_framework_marker_keeps_later_independent_order_total():
    result = extract_element_result(_parsed(
        "本框架协议不设固定总额。暂估采购额为100万元。\n"
        "独立订单合同总价为人民币42万元，订单服务费为10万元。"
    ))

    assert result.values["amount"] == "人民币42万元"
    assert "amount" not in result.review_fields


def test_different_strong_totals_require_manual_review():
    result = extract_element_result(_parsed("合同总价为100万元。补充条款约定合同总额为120万元。"))

    assert result.values["amount"] == "100万元"
    assert "amount" in result.review_fields
    assert result.evidence["amount"].validation == "ambiguous"


@pytest.mark.parametrize("later_total", [
    "总价为120万元",
    "补充协议约定包干总价为120万元",
])
def test_different_total_price_labels_still_require_manual_review(later_total):
    result = extract_element_result(_parsed(f"合同总价为100万元。{later_total}。"))

    assert result.values["amount"] == "100万元"
    assert "amount" in result.review_fields
    assert result.evidence["amount"].validation == "ambiguous"


def test_plain_total_before_guarantee_in_next_clause_remains_contract_amount():
    result = extract_element_result(_parsed("总价为100万元，履约保证金为10万元。"))

    assert result.values["amount"] == "100万元"
    assert result.evidence["amount"].validation == "valid"
    assert "amount" not in result.review_fields


def test_supplemental_total_before_guarantee_still_requires_amount_review():
    result = extract_element_result(_parsed(
        "合同总价为100万元。补充协议总价为120万元，履约保证金为10万元。"
    ))

    assert result.values["amount"] == "100万元"
    assert result.evidence["amount"].validation == "ambiguous"
    assert "amount" in result.review_fields


@pytest.mark.parametrize("preceding_clause", [
    "履约保证金为10万元",
    "单价为20元/件",
])
def test_plain_total_after_unrelated_money_keeps_its_local_semantics(preceding_clause):
    result = extract_element_result(_parsed(f"{preceding_clause}，总价为100万元。"))

    assert result.values["amount"] == "100万元"
    assert result.evidence["amount"].validation == "valid"
    assert "amount" not in result.review_fields


def test_total_after_guarantee_can_conflict_with_previous_contract_total():
    result = extract_element_result(_parsed(
        "合同总价为80万元。履约保证金为10万元，总价为100万元。"
    ))

    assert result.values["amount"] == "80万元"
    assert result.evidence["amount"].validation == "ambiguous"
    assert "amount" in result.review_fields


@pytest.mark.parametrize("repeated_term", [
    "2026年1月1日至2027年1月1日",
    "自2026-01-01起至2027-01-01止",
    "2026/1/1至2027/1/1",
])
def test_equivalent_service_and_contract_dates_keep_valid_source_evidence(repeated_term):
    raw_term = "自2026年1月1日起\n至2027年1月1日止"
    text = f"服务期限{raw_term}。\n合同期限：{repeated_term}。"
    parsed = DocumentParseResult(
        text=text,
        source="native",
        blocks=(DocumentBlock("p2", "page_text", text, SourceAnchor(page_number=2)),),
    )

    result = extract_element_result(parsed)

    evidence = result.evidence["duration"]
    assert result.values["duration"] == raw_term
    assert evidence.raw_text == raw_term
    assert text[evidence.start:evidence.end] == raw_term
    assert evidence.page == 2
    assert evidence.validation == "valid"
    assert "duration" not in result.review_fields


def test_different_service_and_contract_dates_remain_ambiguous():
    result = extract_element_result(_parsed(
        "服务期限自2026年1月1日起至2027年1月1日止。"
        "合同期限：2026-01-01至2027-02-01。"
    ))

    assert "duration" in result.review_fields
    assert result.evidence["duration"].validation == "ambiguous"


@pytest.mark.parametrize("term", [
    "自2026-1-1起至2027-01-01止",
    "自2026/01/01起至2027/1/1止",
    "自2026.1.1起至2027年1月1日止",
])
def test_service_date_formats_do_not_include_payment_deadline(term):
    result = extract_element_result(_parsed(f"服务期限{term}，验收后30日内付款。"))

    assert result.values["duration"] == term
    assert "30日" not in result.evidence["duration"].raw_text
    assert "duration" not in result.review_fields


@pytest.mark.parametrize(("label", "term"), [
    ("履行期限为", "两年"),
    ("合同期限：", "十八个月"),
    ("服务期为", "90日"),
    ("服务期限", "自合同签订之日起2年"),
    ("服务期限", "自合同生效之日起十二个月"),
])
def test_chinese_and_arabic_relative_terms_exclude_payment_deadline(label, term):
    result = extract_element_result(_parsed(f"{label}{term}，验收后30日内付款。"))

    assert result.values["duration"] == term
    assert "30日" not in result.evidence["duration"].raw_text
    assert "duration" not in result.review_fields


@pytest.mark.parametrize("pages", [(3, 3), (3, 4)])
def test_multiline_term_retains_exact_range_and_page_ambiguity(pages):
    parts = ("服务期限自2026/1/1起", "至2027/1/1止，验收后30日内付款。")
    text = "\n".join(parts)
    parsed = DocumentParseResult(
        text=text,
        source="native",
        blocks=tuple(
            DocumentBlock(f"b{index}", "paragraph", part, SourceAnchor(page_number=page))
            for index, (part, page) in enumerate(zip(parts, pages))
        ),
    )

    result = extract_element_result(parsed)

    evidence = result.evidence["duration"]
    assert evidence.raw_text == "自2026/1/1起\n至2027/1/1止"
    assert text[evidence.start:evidence.end] == evidence.raw_text
    assert evidence.page == (3 if pages[0] == pages[1] else None)
    assert evidence.validation == ("valid" if pages[0] == pages[1] else "ambiguous")
    assert ("duration" in result.review_fields) == (pages[0] != pages[1])
