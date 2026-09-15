# 2026-09-15 RAG 修复回归测试：
# 1. 条号精确短路只对简短显式法条查询触发，grounding 拼接查询不得被劫持
# 2. 确定性精排如实标注排序口径（ordering 字段）
# 3. 本地 bge embedding 查询侧加检索指令前缀
# 4. 显式知识导入默认 global 可检索，unclassified 如实告警
import json
from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1.endpoints import knowledge
from app.db.session import Base
from app.models.models import KnowledgeChunk, LegalArticle, LegalSource
from app.schemas.contract import KnowledgeImport
from app.services.rag import retriever


@pytest.fixture
def retrieval_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(retriever, "SessionLocal", factory)
    try:
        yield factory
    finally:
        retriever._bm25_cache = None
        engine.dispose()


def _seed_article_585(factory) -> None:
    with factory() as db:
        db.add(LegalSource(
            source_id="source-585",
            title="中华人民共和国民法典",
            issuing_authority="全国人民代表大会",
            official_url="https://flk.npc.gov.cn/example",
            publication_date=date(2020, 5, 28),
            effective_date=date(2021, 1, 1),
            version_status="现行有效",
            retrieved_at=date(2026, 9, 8),
            file_sha256="a" * 64,
        ))
        db.add(LegalArticle(
            id=585,
            source_id="source-585",
            article_number="第五百八十五条",
            article_sort=585000,
            chapter_title="第三编 合同",
            content="第五百八十五条 当事人可以约定违约金。",
            content_hash="b" * 64,
        ))
        db.add(KnowledgeChunk(
            id=11,
            category="law",
            source="中华人民共和国民法典",
            content="第五百八十五条 当事人可以约定违约金。",
            embedding="",
            article_number="第五百八十五条",
            version="2020",
            effective_date=date(2021, 1, 1),
            expiry_date=None,
            applicable_contract_types="[]",
            applicable_dimensions="[]",
            scope_mode="global",
            legal_article_id=585,
            chunk_index=0,
            chunk_count=1,
        ))
        db.commit()


class TestExactRouteGating:
    """P0-1：条号短路不得劫持拼接了合同原文的长查询。"""

    def test_long_query_with_contract_clause_number_uses_hybrid(self, retrieval_db):
        """grounding 风格查询（类别+合同原文+原因，含"第五百八十五条"字样但超长）走混合检索。"""
        _seed_article_585(retrieval_db)
        clause = "第五条 乙方应在验收合格后30日内支付全部款项，逾期按日万分之五支付违约金。"
        long_query = "违约责任 " + clause * 3 + " 付款周期与违约金比例存在风险"
        assert "第五条" in long_query and len(long_query) > 40

        with (
            patch.object(retriever, "_bm25_search", return_value={11: 0}) as bm25,
            patch.object(retriever, "_vector_search", return_value={11: 0}),
        ):
            results = retriever.retrieve(long_query, top_k=3)

        bm25.assert_called_once()
        assert all(item["retrieval_mode"] != "exact" for item in results)

    def test_allow_exact_false_disables_short_exact_query(self, retrieval_db):
        """grounding 显式传 allow_exact=False 时，即使查询是短条号也走混合检索。"""
        _seed_article_585(retrieval_db)

        with (
            patch.object(retriever, "_bm25_search", return_value={11: 0}) as bm25,
            patch.object(retriever, "_vector_search", return_value={11: 0}),
        ):
            results = retriever.retrieve("第五百八十五条", top_k=3, allow_exact=False)

        bm25.assert_called_once()
        assert results and results[0]["retrieval_mode"] != "exact"

    def test_short_explicit_article_query_still_exact(self, retrieval_db):
        """简短显式法条查询保持 exact 短路（原有行为不回归）。"""
        _seed_article_585(retrieval_db)

        with patch.object(
            retriever, "_bm25_search", side_effect=AssertionError("精确条号不应走 BM25")
        ):
            results = retriever.retrieve("请查询民法典第585条", top_k=3)

        assert len(results) == 1
        assert results[0]["retrieval_mode"] == "exact"
        assert results[0]["article_number"] == "第五百八十五条"

    def test_grounding_passes_allow_exact_false(self):
        """auditor._ground_risks 的 retrieve 调用必须关闭条号短路。"""
        from app.services.audit import auditor

        calls: list[dict] = []

        def fake_retrieve(query, **kwargs):
            calls.append(kwargs)
            return []

        risk = {
            "category": "违约责任",
            "original_text": "第五条 乙方逾期付款应支付违约金。",
            "risk_reason": "违约金比例过高",
            "claim_id": "C-TEST",
            "confidence": 0,
        }
        with patch.object(auditor, "retrieve", side_effect=fake_retrieve):
            auditor._ground_risks([risk], contract_text="第五条 乙方逾期付款应支付违约金。")

        assert calls, "grounding 应至少调用一次 retrieve"
        assert all(call.get("allow_exact") is False for call in calls)


class TestRerankOrderingHonesty:
    """P0-2：trace 必须如实标注排序口径。"""

    def _candidates(self):
        return [
            {"chunk_id": 1, "content": "候选甲", "matched_content": "候选甲", "score": 0.2},
            {"chunk_id": 2, "content": "候选乙", "matched_content": "候选乙", "score": 0.1},
        ]

    def test_deterministic_mode_marks_rrf_preserved(self):
        ranked = retriever.rerank_results("查询", self._candidates(), route_ranks={}, top_k=2)

        assert all(
            item["retrieval_trace"]["ordering"] == "rrf_preserved" for item in ranked
        )
        # 保留融合顺序的设计不变：不按 rerank_score 重排
        assert [item["chunk_id"] for item in ranked] == [1, 2]

    def test_cross_encoder_mode_marks_rerank_score_desc(self):
        ranked = retriever.rerank_results(
            "查询",
            self._candidates(),
            route_ranks={},
            top_k=2,
            scorer=lambda _q, docs: [0.1 if text == "候选甲" else 0.9 for text in docs],
        )

        assert [item["chunk_id"] for item in ranked] == [2, 1]
        assert all(
            item["retrieval_trace"]["ordering"] == "rerank_score_desc" for item in ranked
        )


class _CapturingEmbeddingAdapter:
    def __init__(self):
        self.texts: list[str] = []

    def embed(self, texts):
        self.texts.extend(texts)
        return [[1.0, 0.0] for _ in texts]


class TestBgeQueryPrefix:
    """P1-3：本地 bge 查询侧加指令前缀，API 后端不加。"""

    def _docs(self):
        return [(
            1, "违约责任", "来源", json.dumps([1.0, 0.0]), "law", None, None,
            None, None, "[]", "[]", retriever.settings.LOCAL_EMBED_MODEL, 2,
        )]

    def test_local_backend_prefixes_query(self):
        adapter = _CapturingEmbeddingAdapter()
        with (
            patch.object(retriever, "get_embedding_adapter", return_value=adapter),
            patch.object(retriever.settings, "EMBED_BACKEND", "local"),
        ):
            retriever._vector_search("违约责任", self._docs())

        assert adapter.texts == [
            retriever.settings.EMBED_QUERY_PREFIX + "违约责任"
        ]

    def test_api_backend_does_not_prefix_query(self):
        adapter = _CapturingEmbeddingAdapter()
        with (
            patch.object(retriever, "get_embedding_adapter", return_value=adapter),
            patch.object(retriever.settings, "EMBED_BACKEND", "api"),
        ):
            retriever._vector_search("违约责任", self._docs())

        assert adapter.texts == ["违约责任"]

    def test_empty_prefix_config_disables_prefix(self):
        adapter = _CapturingEmbeddingAdapter()
        with (
            patch.object(retriever, "get_embedding_adapter", return_value=adapter),
            patch.object(retriever.settings, "EMBED_BACKEND", "local"),
            patch.object(retriever.settings, "EMBED_QUERY_PREFIX", ""),
        ):
            retriever._vector_search("违约责任", self._docs())

        assert adapter.texts == ["违约责任"]


class TestImportScopeVisibility:
    """P1-6：显式导入默认 global 可检索；unclassified 如实告警。"""

    def test_knowledge_import_schema_defaults_to_global(self):
        assert KnowledgeImport(content="某条规则").scope_mode == "global"

    def test_scope_visibility_warns_on_unclassified(self):
        visibility = knowledge._scope_visibility("unclassified")

        assert visibility["retrievable"] is False
        assert visibility["scope_warning"]

    @pytest.mark.parametrize("mode", ["global", "scoped"])
    def test_scope_visibility_ok_on_retrievable_modes(self, mode):
        visibility = knowledge._scope_visibility(mode)

        assert visibility["retrievable"] is True
        assert visibility["scope_warning"] is None
