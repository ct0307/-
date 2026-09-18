"""统一确定性规则执行器测试。"""

import pytest

from app.services.audit.rules import executor
from app.services.audit.rules.executor import execute_rule
from app.services.audit.rules.schema import RuleDefinition


def _payment_rule() -> RuleDefinition:
    return RuleDefinition(
        rule_id="FIN-PAYMENT-TOTAL-001",
        version="1.0.0",
        name="付款比例合计检查",
        category="numeric",
        agent="finance",
        dimensions=("payment",),
        contract_types=("采购合同",),
        severity="high",
        handler="payment_total",
    )


@pytest.mark.parametrize(("facts", "status", "reason_code"), [
    ({"payment_percentages": [30, 70]}, "not_hit", "PAYMENT_TOTAL_EQUALS_100"),
    ({"payment_percentages": [50, 60]}, "hit", "PAYMENT_TOTAL_EXCEEDS_100"),
    ({"payment_percentages": []}, "unclear", "PAYMENT_PERCENTAGES_MISSING"),
])
def test_payment_total_rule(facts, status, reason_code):
    result = execute_rule(_payment_rule(), facts)

    assert result.status == status
    assert result.reason_code == reason_code
    assert result.rule_id == "FIN-PAYMENT-TOTAL-001"
    assert result.rule_version == "1.0.0"


def test_payment_total_rule_records_calculation_trace():
    result = execute_rule(
        _payment_rule(),
        {"payment_percentages": ["50", "60"], "clause_ids": ["C-3", "C-4"]},
    )

    assert result.status == "hit"
    assert result.clause_ids == ["C-3", "C-4"]
    assert result.facts == {"percentages": ["50", "60"], "total": "110"}
    assert result.calculation == "50 + 60 = 110"


def test_handler_exception_returns_controlled_error_without_leaking_text(monkeypatch):
    def fail(_rule, _facts):
        raise RuntimeError("数据库密码 secret-value")

    monkeypatch.setitem(executor.HANDLERS, "payment_total", fail)

    result = execute_rule(_payment_rule(), {"payment_percentages": [50, 50]})

    assert result.status == "error"
    assert result.reason_code == "RULE_EXECUTION_FAILED"
    assert "secret-value" not in result.model_dump_json()


def test_legacy_deterministic_findings_are_mapped_from_rule_hits():
    from app.services.audit.deterministic_checks import find_deterministic_findings

    text = (
        "乙方（承包方）：\n"
        "甲方将  项目的部分劳务工作交由乙方完成\n"
        "甲方于每月  日前以  方式支付劳务费用。\n"
        "甲方不承担乙方在提供劳务过程中的工伤、意外伤害等任何责任。"
    )

    findings = find_deterministic_findings(text)

    assert [finding.category for finding in findings] == [
        "合同主体信息缺失",
        "工作范围约定缺失",
        "付款日期及方式缺失",
        "人身损害免责责任风险",
    ]
    assert all(finding.quote in text for finding in findings)
