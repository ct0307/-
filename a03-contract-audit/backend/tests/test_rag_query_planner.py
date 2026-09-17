"""结构化 Claim 的可审计检索查询计划。"""

from app.services.audit.claims import AuditClaim
from app.services.rag.query_planner import plan_claim, rewrite_evidence_query


def test_plan_claim_builds_legal_fact_and_applicability_queries():
    claim = AuditClaim(
        agent="finance",
        level="medium",
        category="付款条件不明确",
        dimension="payment",
        action="支付尾款",
        condition="验收完成",
        consequence="支付20%合同款",
        quote="验收完成后支付剩余款项",
        clause_ids=["C-18"],
    )

    plan = plan_claim(claim, contract_type="采购合同")

    assert [query.kind for query in plan.queries] == [
        "legal_issue",
        "fact_pattern",
        "applicability",
    ]
    assert all(query.contract_type == "采购合同" for query in plan.queries)
    assert all(query.dimensions == ("payment",) for query in plan.queries)
    assert plan.claim_id == claim.claim_id
    assert plan.max_rewrites == 1
    assert plan.version == "query-plan-v1"


def test_plan_claim_uses_only_exact_query_for_explicit_legal_article():
    claim = AuditClaim(
        agent="legal",
        level="high",
        category="违约金适用《民法典》第五百八十五条",
        dimension="breach",
        quote="违约方应按合同金额支付违约金",
    )

    plan = plan_claim(claim, contract_type="采购合同")

    assert [(query.kind, query.text) for query in plan.queries] == [
        ("exact_reference", "《民法典》第五百八十五条"),
    ]


def test_plan_claim_does_not_treat_contract_clause_number_as_legal_reference():
    claim = AuditClaim(
        agent="legal",
        level="medium",
        category="违约责任不明确",
        dimension="breach",
        quote="第五条 乙方逾期付款应支付违约金",
    )

    plan = plan_claim(claim, contract_type="采购合同")

    assert [query.kind for query in plan.queries] == [
        "legal_issue", "fact_pattern", "applicability"
    ]


def test_plan_claim_uses_absence_requirement_for_missing_information():
    claim = AuditClaim(
        agent="finance",
        level="medium",
        category="付款条件缺失",
        dimension="payment",
        quote="验收后支付剩余款项",
        missing_information=["付款期限", "发票类型"],
    )

    plan = plan_claim(claim, contract_type="采购合同")

    assert [query.kind for query in plan.queries] == ["absence_requirement"]
    assert "付款期限" in plan.queries[0].text
    assert "发票类型" in plan.queries[0].text


def test_rewrite_evidence_query_only_accepts_controlled_failure_codes():
    claim = AuditClaim(
        agent="finance",
        level="medium",
        category="付款条件不明确",
        dimension="payment",
        quote="验收后支付剩余款项",
    )
    query = plan_claim(claim, contract_type="采购合同").queries[0]

    rewritten = rewrite_evidence_query(query, "INSUFFICIENT_SUPPORT")

    assert rewritten is not None
    assert rewritten.text != query.text
    assert rewrite_evidence_query(query, "模型自由文本") is None


def test_rewrite_evidence_query_never_rewrites_exact_article_reference():
    claim = AuditClaim(
        agent="legal",
        level="high",
        category="违约金适用《民法典》第五百八十五条",
        dimension="breach",
        quote="违约方应按合同金额支付违约金",
    )
    query = plan_claim(claim).queries[0]

    assert rewrite_evidence_query(query, "INSUFFICIENT_SUPPORT") is None
