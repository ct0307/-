"""合同类型分类器的确定性行为。"""

import pytest

from app.services.imports.classifier import classify_contract_type


TYPES = ["采购合同", "软件开发外包合同", "劳动合同", "租赁合同", "保密协议"]
ALL_TYPES = [
    "软件开发外包合同", "技术服务合同", "采购合同", "销售合同", "劳动合同",
    "租赁合同", "保密协议", "合作协议", "服务协议", "框架协议",
    "技术开发合同", "合作合同", "服务合同", "劳务合同",
]


def test_classifies_purchase_contract_with_high_confidence():
    result = classify_contract_type(
        filename="设备采购合同.pdf",
        text="甲方向乙方采购服务器设备，乙方负责供货和验收。",
        available_types=TYPES,
    )

    assert result.suggested_type == "采购合同"
    assert result.confidence >= 0.85
    assert "采购" in result.evidence


def test_returns_no_selection_when_evidence_is_too_weak():
    result = classify_contract_type(
        filename="扫描件03.pdf",
        text="双方经协商一致订立本文件。",
        available_types=TYPES,
    )

    assert result.suggested_type == ""
    assert result.confidence < 0.60


def test_only_returns_an_available_contract_type():
    result = classify_contract_type(
        filename="系统开发协议.docx",
        text="交付源代码并完成软件系统开发。",
        available_types=["技术开发合同", "采购合同"],
    )

    assert result.suggested_type == "技术开发合同"


@pytest.mark.parametrize("contract_type", ALL_TYPES)
def test_every_configured_type_is_reachable_by_its_title(contract_type):
    result = classify_contract_type(
        filename=f"{contract_type}.pdf", text=f"{contract_type}\n甲乙双方订立本合同。",
        available_types=ALL_TYPES,
    )

    assert result.suggested_type == contract_type
    assert result.candidates[0].contract_type == contract_type
    assert result.candidates[0].score > 0
    assert len(result.candidates) <= 3
    assert result.auto_ready_eligible is True


def test_filename_trade_signal_outweighs_generic_confidentiality_clause():
    result = classify_contract_type(
        filename="设备采购合同.pdf",
        text="双方对商业秘密承担保密义务，违反约定承担违约责任，争议协商解决。",
        available_types=ALL_TYPES,
    )

    assert result.suggested_type == "采购合同"
    assert result.candidates[0].contract_type == "采购合同"
    assert all(candidate.score <= 0.25 for candidate in result.candidates if candidate.contract_type == "保密协议")


def test_only_generic_clauses_cannot_become_high_confidence_or_auto_ready():
    result = classify_contract_type(
        filename="扫描件.pdf",
        text="双方承担保密义务，违约责任和争议解决依照本协议约定。",
        available_types=ALL_TYPES,
    )

    assert result.confidence < 0.60
    assert result.auto_ready_eligible is False


def test_candidates_are_stably_sorted_and_exclude_nonpositive_scores():
    result = classify_contract_type(
        filename="扫描件.pdf", text="采购设备并销售产品。", available_types=ALL_TYPES,
    )

    assert result.candidates == tuple(sorted(result.candidates, key=lambda item: (-item.score, item.contract_type)))
    assert all(candidate.score > 0 for candidate in result.candidates)


def test_trade_signal_at_character_300_is_in_lead_not_body():
    result = classify_contract_type(
        filename="扫描件.pdf", text="背景\n" + "甲" * 300 + "采购设备",
        available_types=["采购合同"],
    )

    assert result.candidates[0].score == 3


def test_trade_signal_after_lead_is_only_body_weight():
    result = classify_contract_type(
        filename="扫描件.pdf", text="背景\n" + "甲" * 1800 + "采购设备",
        available_types=["采购合同"],
    )

    assert result.candidates[0].score == 1


@pytest.mark.parametrize(
    "body", ["双方订立本合同。", "背景\n" + "甲" * 1800 + "采购设备"],
    ids=["tied", "near-tied"],
)
def test_tied_or_near_tied_types_cannot_auto_ready(body):
    result = classify_contract_type(
        filename="采购合同-销售合同.pdf", text=body,
        available_types=["采购合同", "销售合同"],
    )

    assert result.candidates[0].score >= 6
    assert result.candidates[1].score >= 6
    assert result.confidence < 0.85
    assert result.auto_ready_eligible is False
