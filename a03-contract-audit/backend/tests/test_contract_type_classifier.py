"""合同类型分类器的确定性行为。"""

from app.services.imports.classifier import classify_contract_type


TYPES = ["采购合同", "软件开发外包合同", "劳动合同", "租赁合同", "保密协议"]


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
