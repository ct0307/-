# RAG 混合检索单元测试：RRF 融合 / 分词 / BM25 排名 / 降级
from app.services.rag import retriever
from app.services.rag.retriever import (
    _keyword_search,
    _rrf_fuse,
    _tokenize,
)


def test_tokenize_chinese():
    """jieba 分词切出法律术语。"""
    tokens = _tokenize("当事人应当承担违约责任并支付违约金")
    assert "违约" in tokens or "违约责任" in tokens
    assert "违约金" in tokens
    # 无空白 token
    assert all(t.strip() for t in tokens)


def test_tokenize_empty():
    """空/纯空白文本分词为空。"""
    assert _tokenize("   ") == []
    assert _tokenize("") == []


def test_rrf_fuse_basic():
    """RRF 融合：两路都靠前的 doc 融合分最高。"""
    vec = {1: 0, 2: 1, 3: 2}   # doc1 向量第1
    bm25 = {2: 0, 1: 1, 4: 2}  # doc2 BM25第1
    fused = _rrf_fuse([vec, bm25])
    ids = [doc_id for doc_id, _ in fused]
    # doc1(rank0+rank1) 和 doc2(rank1+rank0) 两路都命中，应排在只单路命中的 doc3/doc4 前
    assert set(ids[:2]) == {1, 2}
    assert 3 in ids and 4 in ids


def test_rrf_fuse_score_order():
    """两路均第1的 doc 融合分 > 单路第1的 doc。"""
    both_first = _rrf_fuse([{1: 0}, {1: 0}])[0][1]  # doc1 两路都第1
    one_first = _rrf_fuse([{2: 0}, {3: 0}])[0][1]   # doc2 单路第1
    assert both_first > one_first


def test_rrf_fuse_empty():
    """空输入返回空。"""
    assert _rrf_fuse([{}, {}]) == []


def test_keyword_fallback():
    """降级关键词命中：命中多的排前。"""
    res = _keyword_search("违约 违约责任 违约金 争议", top_k=3)
    assert len(res) >= 1
    # 违约类命中3词，应排第一
    assert "违约" in res[0]["content"]
    assert all("score" in r and "content" in r and "source" in r for r in res)
    assert res[0]["matched_content"] == res[0]["content"]
    assert res[0]["legal_article_id"] is None


def test_bm25_index_cache_fingerprint():
    """BM25 索引指纹缓存：同指纹复用，不同指纹重建。"""
    retriever._bm25_cache = None
    docs1 = [(1, "违约责任条款", "src1", ""), (2, "争议解决条款", "src2", "")]
    bm25_a, ids_a = retriever._get_bm25_index(docs1)
    bm25_b, ids_b = retriever._get_bm25_index(docs1)
    assert bm25_a is bm25_b  # 同指纹复用同一对象
    # 新增一条 → 指纹变 → 重建
    docs2 = docs1 + [(3, "付款方式条款", "src3", "")]
    bm25_c, ids_c = retriever._get_bm25_index(docs2)
    assert bm25_c is not bm25_a
    assert len(ids_c) == 3
    retriever._bm25_cache = None  # 清理，不污染其他用例


def test_bm25_search_ranks_relevant_first():
    """BM25 检索：含 query 词的切片排在前。"""
    retriever._bm25_cache = None
    docs = [
        (1, "当事人应当承担违约责任并支付违约金", "民法典577", ""),
        (2, "合同争议提交仲裁机构解决", "民法典502", ""),
        (3, "合同标的物的质量应当符合约定", "民法典615", ""),
    ]
    rank = retriever._bm25_search("违约金 违约责任", docs)
    # doc1 最相关，应 rank 最小
    assert rank.get(1) == 0
    retriever._bm25_cache = None


def test_bm25_search_no_hit():
    """query 无词命中语料时返回空。"""
    retriever._bm25_cache = None
    docs = [(1, "违约责任条款", "src", "")]
    rank = retriever._bm25_search("xyzabc", docs)  # 无中文词命中
    assert rank == {}
    retriever._bm25_cache = None


def test_query_plan_expands_payment_and_acceptance_terms_deterministically():
    plan = retriever.build_query_plan("验收后付款期限是否明确")

    assert plan.original_query == "验收后付款期限是否明确"
    assert "支付条件" in plan.expanded_terms
    assert "验收标准" in plan.expanded_terms
    assert plan.article_number is None
    assert retriever.build_query_plan("验收后付款期限是否明确") == plan


def test_query_plan_keeps_exact_article_route():
    plan = retriever.build_query_plan("民法典第585条对违约金如何规定")

    assert plan.article_number == "第五百八十五条"
    assert "违约责任" in plan.expanded_terms


def test_evidence_rerank_fallback_scores_coverage_without_overriding_rrf_order():
    candidates = [
        {
            "chunk_id": 1,
            "content": "合同当事人应当全面履行义务。",
            "matched_content": "合同当事人应当全面履行义务。",
            "source": "通用规则",
            "score": 0.04,
        },
        {
            "chunk_id": 2,
            "content": "付款条件应明确验收标准、验收期限和支付时间。",
            "matched_content": "付款条件应明确验收标准、验收期限和支付时间。",
            "source": "付款审查规则",
            "score": 0.03,
        },
    ]
    route_ranks = {
        1: {"bm25_rank": 0, "vector_rank": 0},
        2: {"bm25_rank": 1, "vector_rank": 1},
    }

    ranked = retriever.rerank_results(
        "验收后付款期限",
        candidates,
        route_ranks=route_ranks,
        top_k=2,
    )

    assert [item["chunk_id"] for item in ranked] == [1, 2]
    assert ranked[0]["retrieval_trace"]["routes"] == route_ranks[1]
    assert ranked[0]["retrieval_trace"]["rerank_mode"] == "deterministic_evidence_v1"
    assert ranked[0]["retrieval_trace"]["rrf_score"] == 0.04
    assert (
        ranked[1]["retrieval_trace"]["rerank_score"]
        > ranked[0]["retrieval_trace"]["rerank_score"]
    )


def test_evidence_rerank_accepts_cross_encoder_scorer_without_changing_contract():
    candidates = [
        {"chunk_id": 1, "content": "候选甲", "matched_content": "候选甲", "score": 0.2},
        {"chunk_id": 2, "content": "候选乙", "matched_content": "候选乙", "score": 0.1},
    ]

    ranked = retriever.rerank_results(
        "查询",
        candidates,
        route_ranks={},
        top_k=2,
        scorer=lambda _query, documents: [0.1 if text == "候选甲" else 0.9 for text in documents],
    )

    assert [item["chunk_id"] for item in ranked] == [2, 1]
    assert ranked[0]["retrieval_trace"]["rerank_mode"] == "cross_encoder"
