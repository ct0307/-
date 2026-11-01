from decimal import Decimal
import pytest

from app.services.audit import auditor


def test_detects_conflicting_payment_deadlines_for_same_trigger():
    from app.services.audit.contract_logic import detect_clause_conflicts

    text = """第一条 甲方应在验收合格后10日内支付合同款。
第二条 甲方应在验收合格后30日内完成付款。
第三条 乙方应在合同签订后5日内进场。"""

    conflicts = detect_clause_conflicts(text)

    assert len(conflicts) == 1
    assert conflicts[0].category == "付款期限冲突"
    assert conflicts[0].clause_ids == ("第一条", "第二条")
    assert set(conflicts[0].values) == {"10日", "30日"}


def test_different_payment_triggers_are_not_reported_as_direct_conflict():
    from app.services.audit.contract_logic import detect_clause_conflicts

    text = """第一条 甲方应在合同签订后10日内支付预付款。
第二条 甲方应在验收合格后30日内支付尾款。"""

    assert detect_clause_conflicts(text) == []


def test_payment_schedule_calculates_percentage_total():
    from app.services.audit.contract_logic import analyze_payment_schedule

    balanced = analyze_payment_schedule(
        "第一条 合同签订后支付合同总价的30%预付款。\n第二条 验收后支付合同总价的70%尾款。"
    )
    incomplete = analyze_payment_schedule(
        "第一条 合同签订后支付合同总价的30%预付款。\n第二条 验收后支付合同总价的60%尾款。"
    )

    assert balanced.status == "balanced"
    assert balanced.total_percentage == Decimal("100")
    assert incomplete.status == "incomplete"
    assert incomplete.total_percentage == Decimal("90")
    assert incomplete.clause_ids == ("第一条", "第二条")


def test_penalty_calculation_is_decimal_and_cap_aware():
    from app.services.audit.contract_logic import calculate_penalty

    assert calculate_penalty("100000", "0.001", 10) == Decimal("1000.00")
    assert calculate_penalty("100000", "0.01", 50, cap_rate="0.2") == Decimal("20000.00")


def test_audit_contract_surfaces_deterministic_logic_conflicts(monkeypatch):
    monkeypatch.setattr(auditor, "_agent_audit", lambda *_args, **_kwargs: auditor.AgentAuditResult([], [], 1, 1))
    text = """第一条 甲方应在验收合格后10日内支付合同款。
第二条 甲方应在验收合格后30日内完成付款。"""

    result = auditor.audit_contract({}, text)

    logic_checks = [item for item in result["cross_checks"] if item["id"].startswith("LC-")]
    assert len(logic_checks) == 1
    assert logic_checks[0]["verdict"] == "conflict"
    assert logic_checks[0]["evidence_clause_ids"] == ["第一条", "第二条"]


def test_candidate_dimension_validation_rejects_cross_dimension_and_unknown_categories():
    from app.services.audit.contract_logic import candidate_dimensions

    payment = {
        "category": "付款金额风险",
        "original_text": "合同金额为100万元。",
        "risk_reason": "付款金额约定不清。",
        "suggestion": "明确金额及权利义务。",
    }
    unknown = {
        "category": "其他事项",
        "original_text": "其他事项。",
        "risk_reason": "需要关注。",
        "suggestion": "请复核。",
    }

    assert candidate_dimensions(payment) == {"payment"}
    assert candidate_dimensions(unknown) == set()
    assert auditor._candidate_matches_dimensions(payment, "legal", ["legal"]) is False
    assert auditor._candidate_matches_dimensions(unknown, "legal", []) is False


def test_deterministic_fact_validation_rejects_false_amount_mismatch_and_invented_date():
    from app.services.audit.contract_logic import validate_candidate_facts

    text = (
        "第一条 合同金额为人民币100万元（大写：人民币壹佰万元整）。\n"
        "第二条 签订日期：2026年9月14日。"
    )
    false_mismatch = {
        "category": "大小写金额不一致",
        "original_text": "合同金额为人民币100万元（大写：人民币壹佰万元整）。",
        "risk_reason": "小写100万元与大写壹佰万元不一致。",
    }
    invented_date = {
        "category": "签订日期风险",
        "original_text": "签订日期：2026年9月14日。",
        "risk_reason": "合同签订日期为2026年9月15日。",
    }
    invented_amount = {
        "category": "合同金额风险",
        "original_text": "合同金额为人民币100万元。",
        "risk_reason": "合同金额为人民币200万元。",
    }

    assert validate_candidate_facts(false_mismatch, text).valid is False
    assert validate_candidate_facts(invented_date, text).valid is False
    assert validate_candidate_facts(invented_amount, text).valid is False


@pytest.mark.parametrize('amount,valid', [('504000元', True), ('50.4万元', True), ('604000元', False)])
def test_fact_validation_accepts_only_exact_quantity_times_unit_price(amount, valid):
    from app.services.audit.contract_logic import validate_candidate_facts
    text = '事项｜数量｜单价\n备货排产｜4｜人民币126,000元\n部门负责人不超过20万元'
    risk = {'risk_reason': f'模板行金额为{amount}，需核对超限审批路径。'}
    assert validate_candidate_facts(risk, text).valid is valid


@pytest.mark.parametrize('text', [
    '事项｜库存｜单价\n备货排产｜4｜人民币126,000元',
    '事项｜数量｜单价\n备货排产｜4或5｜人民币126,000元',
    '事项｜数量｜单价\n备货排产｜4｜USD126000元',
    '事项｜数量｜单价\n备货排产｜4｜人民币126000元起',
    '事项｜数量｜单价｜币种\n备货排产｜4｜126000元｜美元',
    '事项｜数量｜单价｜折扣\n备货排产｜4｜人民币126000元｜50%',
    '事项｜数量｜单价｜税率\n备货排产｜4｜人民币126000元｜13%',
    '事项｜数量｜单价\n备货排产｜4｜人民币126000元\n其他说明\n另一个表｜6｜人民币84000元',
])
def test_ambiguous_tables_do_not_authorize_derived_amounts(text):
    from app.services.audit.contract_logic import validate_candidate_facts
    amount = '504000元' if '另一个表' not in text else '2016000元'
    assert validate_candidate_facts({'risk_reason': f'总额为{amount}。'}, text).valid is False


def test_derived_amount_is_exact_beyond_default_decimal_precision():
    from app.services.audit.contract_logic import validate_candidate_facts
    text = '事项｜数量｜单价\n备货｜999999999999.999999｜人民币999999999999999999.999999元'
    exact = '999999999999999998999999000000.000000000001'
    rounded = '999999999999999998999999000000'
    assert validate_candidate_facts({'risk_reason': f'行金额为{exact}元。'}, text).valid is True
    assert validate_candidate_facts({'risk_reason': f'行金额为{rounded}元。'}, text).valid is False
