"""结构化证据查询计划执行器测试。"""

from dataclasses import replace
from types import SimpleNamespace

from app.services.rag.query_executor import execute_query_plan
from app.services.rag.query_planner import EvidenceQuery, EvidenceQueryPlan


def _query(kind: str, text: str) -> EvidenceQuery:
    return EvidenceQuery(
        kind=kind,
        text=text,
        contract_type="采购合同",
        dimensions=("payment",),
    )


def test_execute_query_plan_stably_deduplicates_parent_articles_and_keeps_trace():
    plan = EvidenceQueryPlan(
        claim_id="C-TEST",
        queries=(
            _query("legal_issue", "付款期限 法律规则"),
            _query("fact_pattern", "验收后付款"),
        ),
    )

    def search(query):
        chunk_id = 10 if query.kind == "legal_issue" else 11
        return [{
            "chunk_id": chunk_id,
            "legal_article_id": 7,
            "content": "第五百零九条 完整父法条第一款。\n完整父法条第二款。",
            "matched_content": f"命中子块-{query.kind}",
            "source": "民法典",
            "reliable": True,
            "retrieval_mode": "hybrid",
            "applicability_status": "applicable",
            "retrieval_trace": {
                "routes": {"bm25_rank": 1, "vector_rank": 2},
                "rerank_mode": "cross_encoder",
            },
        }]

    result = execute_query_plan(
        plan,
        search=search,
        validate=lambda _sources: SimpleNamespace(
            status="supported", reason_code="EVIDENCE_SUPPORTED"
        ),
        rewrite=lambda _query, _reason_code: None,
    )

    assert len(result.sources) == 1
    assert result.sources[0]["chunk_id"] == 10
    assert result.sources[0]["content"].endswith("完整父法条第二款。")
    assert result.sources[0]["matched_content"] == "命中子块-legal_issue"
    assert [attempt.query_kind for attempt in result.attempts] == [
        "legal_issue", "fact_pattern"
    ]
    assert result.attempts[0].rewrite == 0
    assert result.attempts[0].routes == ({"bm25_rank": 1, "vector_rank": 2},)
    assert result.attempts[0].rerank_mode == "cross_encoder"
    assert result.attempts[0].applicability_status == "applicable"


def test_execute_query_plan_rewrites_each_route_at_most_once_after_failed_round():
    plan = EvidenceQueryPlan(
        claim_id="C-TEST",
        queries=(_query("legal_issue", "付款期限 法律规则"),),
    )
    calls = []

    def search(query):
        calls.append(query.text)
        return [{
            "chunk_id": len(calls),
            "content": query.text,
            "matched_content": query.text,
            "source": "测试来源",
            "reliable": True,
            "retrieval_mode": "bm25",
        }]

    def validate(sources):
        if len(sources) == 1:
            return SimpleNamespace(
                status="unclear", reason_code="INSUFFICIENT_SUPPORT"
            )
        return SimpleNamespace(status="supported", reason_code="EVIDENCE_SUPPORTED")

    result = execute_query_plan(
        plan,
        search=search,
        validate=validate,
        rewrite=lambda query, reason_code: replace(
            query,
            text=f"{query.text} 认定标准" if reason_code == "INSUFFICIENT_SUPPORT" else query.text,
        ),
    )

    assert calls == ["付款期限 法律规则", "付款期限 法律规则 认定标准"]
    assert [attempt.rewrite for attempt in result.attempts] == [0, 1]
    assert result.support_status == "supported"


def test_execute_query_plan_stops_after_second_failed_round():
    plan = EvidenceQueryPlan(
        claim_id="C-TEST",
        queries=(_query("legal_issue", "未知风险 法律规则"),),
    )
    calls = []

    def search(query):
        calls.append(query.text)
        return []

    result = execute_query_plan(
        plan,
        search=search,
        validate=lambda _sources: SimpleNamespace(
            status="unclear", reason_code="INSUFFICIENT_SUPPORT"
        ),
        rewrite=lambda query, _reason_code: replace(query, text=f"{query.text} 改写"),
    )

    assert calls == ["未知风险 法律规则", "未知风险 法律规则 改写"]
    assert len(result.attempts) == 2
    assert result.support_status == "unclear"
