"""保守的付款节点与跨条款检查。"""
import pytest


def test_decimal_schedule_and_original_evidence():
    from app.services.report.payment_insights import analyze_payments
    result = analyze_payments("第一条 签订后支付合同总价的30%。\n第二条 交付后支付合同总价的60%。\n第三条 验收合格后支付合同总价的10%。")
    assert result["status"] == "balanced"
    assert result["total_percentage"] == "100"
    assert len(result["events"]) == 3
    assert result["events"][2]["clause_id"] == "第三条"
    assert "验收合格" in result["events"][2]["quote"]


@pytest.mark.parametrize("text", [
    "支付第一批货款的60%。支付第二批货款的60%。",
    "签订后支付合同总价的30%，也可支付合同总价的50%。",
    "累计支付合同总价的80%。验收后支付合同总价的20%。",
    "支付合同总价的30%。支付合同总价的30%。",
    "支付30%预付款。验收后支付70%尾款。",
    "支付合同总价的30%，其中税率13%。",
    "支付剩余合同金额的30%。支付合同金额的70%。",
])
def test_ambiguous_bases_and_duplicate_or_alternative_terms_are_not_summed(text):
    from app.services.report.payment_insights import analyze_payments
    result = analyze_payments(text)
    assert result["status"] == "needs_review"
    assert result["total_percentage"] is None


def test_excessive_schedule_and_acceptance_conflict():
    from app.services.report.payment_insights import analyze_payments
    result = analyze_payments("第一条 签订后支付合同总价的30%。\n第二条 尾款必须验收合格后支付合同总价的80%。\n第三条 未验收也必须支付尾款。")
    assert result["status"] == "excessive"
    assert result["total_percentage"] == "110"
    issue = next(i for i in result["issues"] if i["kind"] == "acceptance_conflict")
    assert len(issue["quotes"]) == 2


def test_missing_text_is_explicit_and_advance_payment_is_not_a_conflict():
    from app.services.report.payment_insights import analyze_payments
    assert analyze_payments("")["status"] == "unavailable"
    result = analyze_payments("签订后支付合同总价的30%。验收合格后支付合同总价的70%。")
    assert result["issues"] == []


def test_audit_logic_does_not_flag_different_batches_as_overpayment():
    from app.services.audit.contract_logic import build_logic_cross_checks
    assert not [c for c in build_logic_cross_checks("支付第一批货款的60%。支付第二批货款的60%。") if c["id"] == "FC-1"]


def test_contract_amount_is_an_explicit_base_alias():
    from app.services.report.payment_insights import analyze_payments
    result = analyze_payments("第一条 预付款为合同金额的50%。")
    assert result["status"] == "incomplete"
    assert result["total_percentage"] == "50"
