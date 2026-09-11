"""依据内容与风险结论的支持关系校验。"""

from app.services.audit.evidence_validation import (
    SUPPORT_VALIDATOR_VERSION,
    validate_support_relation,
)


def test_explicitly_overlapping_source_is_supported():
    result = validate_support_relation(
        {
            "category": "违约金过高",
            "original_text": "违约金按合同金额的50%计收",
            "risk_reason": "违约金过高可能被调减",
        },
        [
            {
                "content": "约定的违约金过分高于造成的损失，可以请求适当减少。",
                "source": "民法典第五百八十五条",
                "reliable": True,
            }
        ],
    )

    assert result.status == "supported"
    assert result.reason == "风险类别与依据内容存在明确语义重叠"
    assert result.version == SUPPORT_VALIDATOR_VERSION


def test_absence_finding_is_unclear_even_with_reliable_source():
    result = validate_support_relation(
        {
            "category": "条款缺失",
            "original_text": "（全文未检出违约责任相关条款）",
            "risk_reason": "合同未约定违约责任",
        },
        [
            {
                "content": "当事人一方不履行合同义务，应承担违约责任。",
                "source": "民法典第五百七十七条",
                "reliable": True,
            }
        ],
    )

    assert result.status == "unclear"
    assert "缺失类风险" in result.reason


def test_unrelated_source_is_unclear():
    result = validate_support_relation(
        {
            "category": "收款账户不一致",
            "original_text": "收款账户为第三方账户",
            "risk_reason": "收款主体与合同主体不一致",
        },
        [
            {
                "content": "合同应明确履约期限的起止时间。",
                "source": "内置履约期限审查规则",
                "reliable": True,
            }
        ],
    )

    assert result.status == "unclear"
    assert "未发现足够语义重叠" in result.reason


def test_generic_legal_terms_alone_are_unclear():
    result = validate_support_relation(
        {
            "category": "合同责任风险",
            "original_text": "合同责任条款需要审查",
            "risk_reason": "合同责任约定可能存在风险",
        },
        [
            {
                "content": "合同责任应由双方依法承担。",
                "source": "通用合同审查指引",
                "reliable": True,
            }
        ],
    )

    assert result.status == "unclear"
    assert "风险类别锚点" in result.reason


def test_missing_or_unreliable_sources_are_unclear():
    result = validate_support_relation(
        {"category": "付款风险", "original_text": "付款期限不明确"},
        [{"content": "付款条款内容", "source": "旧来源", "reliable": False}],
    )

    assert result.status == "unclear"
    assert "没有可用的可信来源" in result.reason
