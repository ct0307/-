"""首批财务与跨条款规则的行为测试。"""

from app.services.audit.rules.executor import execute_rule
from app.services.audit.rules.schema import RuleDefinition


def _rule(rule_id: str, category: str, handler: str) -> RuleDefinition:
    return RuleDefinition(
        rule_id=rule_id,
        version="1.0.0",
        name=rule_id,
        category=category,
        agent="finance" if rule_id.startswith("FIN-") else "legal",
        dimensions=("payment",),
        severity="high",
        handler=handler,
    )


def test_payment_total_uses_decimal_boundaries():
    rule = _rule("FIN-PAYMENT-TOTAL-002", "numeric", "payment_total")

    below = execute_rule(rule, {"payment_percentages": ["99.99"]})
    equal = execute_rule(rule, {"payment_percentages": ["100"]})
    above = execute_rule(rule, {"payment_percentages": ["100.01"]})

    assert below.status == "unclear"
    assert below.facts["total"] == "99.99"
    assert equal.status == "not_hit"
    assert above.status == "hit"
    assert above.facts["total"] == "100.01"


def test_amount_consistency_normalizes_yuan_wanyuan_and_chinese_uppercase():
    rule = _rule("FIN-AMOUNT-CONSISTENCY-001", "numeric", "amount_consistency")
    result = execute_rule(
        rule,
        {
            "amounts": [
                {"value": "1000000", "unit": "元", "clause_id": "C-1"},
                {"value": "100", "unit": "万元", "clause_id": "C-2"},
                {"value": "人民币壹佰万元整", "clause_id": "C-3"},
            ]
        },
    )

    assert result.status == "not_hit"
    assert result.facts["normalized_amounts"] == ["1000000", "1000000", "1000000"]


def test_amount_consistency_detects_mismatch_between_numeric_and_uppercase():
    rule = _rule("FIN-AMOUNT-CONSISTENCY-001", "numeric", "amount_consistency")
    result = execute_rule(
        rule,
        {
            "amounts": [
                {"value": "1000000", "unit": "元", "clause_id": "C-1"},
                {"value": "人民币玖拾万元整", "clause_id": "C-2"},
            ]
        },
    )

    assert result.status == "hit"
    assert result.reason_code == "AMOUNT_VALUES_MISMATCH"


def test_conditional_or_different_base_payments_are_not_summed():
    rule = _rule("FIN-PAYMENT-TOTAL-002", "numeric", "payment_total")
    result = execute_rule(
        rule,
        {
            "payment_events": [
                {"percentage": "30", "base": "合同总价", "conditional": False},
                {"percentage": "70", "base": "结算价", "conditional": False},
            ]
        },
    )
    assert result.status == "unclear"
    assert result.reason_code == "PAYMENT_BASE_UNCLEAR"

    conditional = execute_rule(
        rule,
        {
            "payment_events": [
                {"percentage": "30", "base": "合同总价", "conditional": True},
                {"percentage": "70", "base": "合同总价", "conditional": False},
            ]
        },
    )
    assert conditional.status == "unclear"
    assert conditional.reason_code == "PAYMENT_CONDITIONAL_UNCLEAR"


def test_payee_consistency_requires_identity_evidence():
    rule = _rule("FIN-PAYEE-CONSISTENCY-001", "cross_clause", "payee_consistency")
    missing = execute_rule(rule, {"payees": []})
    assert missing.status == "unclear"
    assert missing.reason_code == "PAYEE_MISSING"

    same = execute_rule(
        rule,
        {
            "payees": [
                {"name": "杭州甲乙科技有限公司", "credit_code": "91330000123456789A"},
                {"name": " 杭州甲乙科技有限公司 ", "credit_code": "91330000123456789A"},
            ]
        },
    )
    assert same.status == "not_hit"

    different = execute_rule(
        rule,
        {
            "payees": [
                {"name": "杭州甲乙科技有限公司", "credit_code": "91330000123456789A"},
                {"name": "杭州甲乙商贸有限公司", "credit_code": "91330000987654321B"},
            ]
        },
    )
    assert different.status == "hit"
    assert different.reason_code == "PAYEE_IDENTITY_MISMATCH"


def test_date_order_requires_complete_dates_and_flags_performance_before_signing():
    rule = _rule("LEGAL-DATE-ORDER-001", "temporal", "date_order")
    incomplete = execute_rule(rule, {"signing_date": "2026-09", "performance_date": "2026-09-18"})
    assert incomplete.status == "unclear"
    assert incomplete.reason_code == "DATE_INCOMPLETE"

    result = execute_rule(
        rule,
        {"signing_date": "2026-09-18", "performance_date": "2026-09-17"},
    )
    assert result.status == "hit"
    assert result.reason_code == "PERFORMANCE_BEFORE_SIGNING"


def test_payment_deadline_conflict_only_compares_same_trigger():
    rule = _rule("LEGAL-PAYMENT-DEADLINE-001", "cross_clause", "payment_deadline_conflict")
    result = execute_rule(
        rule,
        {
            "payment_deadlines": [
                {"trigger": "验收合格", "deadline": "10日", "clause_id": "C-1"},
                {"trigger": "验收合格", "deadline": "30日", "clause_id": "C-2"},
                {"trigger": "合同签订", "deadline": "5日", "clause_id": "C-3"},
            ]
        },
    )
    assert result.status == "hit"
    assert result.reason_code == "PAYMENT_DEADLINE_CONFLICT"
    assert result.clause_ids == ["C-1", "C-2"]
