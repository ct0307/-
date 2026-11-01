from datetime import date
import hashlib
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.llm.base import LLMError
from app.models.models import KnowledgeChunk, LegalArticle, LegalSource
from app.services.rag import retriever
from app.services.rag.retriever import (
    apply_contract_domain_boost,
    collapse_by_article,
    parse_article_reference,
)


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


def _add_legal_article(
    factory,
    *,
    article_id: int = 585,
    article_number: str = "第五百八十五条",
    content: str = "第五百八十五条 当事人可以约定违约金，并可以请求调整。",
) -> None:
    with factory() as db:
        source_id = f"source-{article_id}"
        db.add(LegalSource(
            source_id=source_id,
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
            id=article_id,
            source_id=source_id,
            article_number=article_number,
            article_sort=article_id * 1000,
            chapter_title="第三编 合同",
            content=content,
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        ))
        db.commit()


def _add_chunk(factory, **overrides) -> None:
    values = {
        "id": 1,
        "category": "law",
        "source": "中华人民共和国民法典",
        "content": "第五百八十五条 当事人可以约定违约金。",
        "embedding": "",
        "article_number": "第五百八十五条",
        "version": "2020",
        "effective_date": date(2021, 1, 1),
        "expiry_date": None,
        "applicable_contract_types": "[]",
        "applicable_dimensions": "[]",
        "scope_mode": "global",
        "legal_article_id": 585,
        "chunk_index": 0,
        "chunk_count": 1,
    }
    with factory() as db:
        db.add(KnowledgeChunk(**{**values, **overrides}))
        db.commit()


@pytest.mark.parametrize(
    "query",
    ["民法典第五百八十五条", "第585条", "585条"],
)
def test_parse_article_reference_normalizes_chinese_and_arabic_numbers(query):
    assert parse_article_reference(query) == "第五百八十五条"


def test_parse_article_reference_ignores_natural_language_without_article_number():
    assert parse_article_reference("违约金约定过高时如何调整") is None


@pytest.mark.parametrize(
    ("query", "expected"),
    [("第2条之一", "第二条之一"), ("第2条之1", "第二条之一"),
     ("第两百条", "第二百条"), ("第2条之两", "第二条之二")],
)
def test_parse_article_reference_preserves_complete_legal_number(query, expected):
    assert parse_article_reference(query) == expected


@pytest.mark.parametrize(
    "query", ["第2条之10000", "第12345条", "第一万条", "第2条之第一万"]
)
def test_parse_article_reference_rejects_partial_number_matches(query):
    assert parse_article_reference(query) is None


def test_collapse_by_article_keeps_best_chunk_and_all_legacy_rows():
    results = [
        {"chunk_id": 11, "legal_article_id": 585, "score": 0.9},
        {"chunk_id": 12, "legal_article_id": 585, "score": 0.8},
        {"chunk_id": 21, "legal_article_id": None, "score": 0.7},
        {"chunk_id": 22, "legal_article_id": None, "score": 0.6},
    ]

    assert collapse_by_article(results) == [results[0], results[2], results[3]]


def test_contract_domain_boost_prioritizes_relevant_civil_code_ranges():
    non_contract = {
        "source": "中华人民共和国民法典",
        "article_number": "第一千零一条",
        "score": 0.03,
    }
    contract = {
        "source": "中华人民共和国民法典",
        "article_number": "第五百七十七条",
        "score": 0.03,
    }

    boosted = apply_contract_domain_boost(
        [non_contract, contract], "合同违约责任如何承担"
    )

    assert boosted == [contract, non_contract]
    assert contract["score"] == 0.03


def test_contract_domain_boost_does_not_override_clear_relevance_gap():
    highly_relevant_non_contract = {
        "source": "中华人民共和国民法典",
        "article_number": "第一千零一条",
        "score": 0.03,
    }
    weak_contract_match = {
        "source": "中华人民共和国民法典",
        "article_number": "第五百七十七条",
        "score": 0.02,
    }

    boosted = apply_contract_domain_boost(
        [highly_relevant_non_contract, weak_contract_match], "合同违约责任如何承担"
    )

    assert boosted == [highly_relevant_non_contract, weak_contract_match]
    assert weak_contract_match["score"] == 0.02


def test_contract_domain_boost_does_not_reorder_unrelated_query():
    original = [
        {"source": "中华人民共和国民法典", "article_number": "第一千零一条", "score": 0.03},
        {"source": "中华人民共和国民法典", "article_number": "第五百七十七条", "score": 0.03},
    ]

    assert apply_contract_domain_boost(original, "人格权受到侵害怎么办") == original


def test_explicit_article_reference_returns_exact_parent_article(retrieval_db):
    parent_content = "第五百八十五条 完整第一款。\n完整第二款。"
    _add_legal_article(retrieval_db, content=parent_content)
    _add_chunk(
        retrieval_db,
        id=11,
        content="第五百八十五条 完整第一款。",
        chunk_index=0,
        chunk_count=2,
    )
    _add_chunk(
        retrieval_db,
        id=12,
        content="完整第二款。",
        chunk_index=1,
        chunk_count=2,
    )

    with patch.object(
        retriever, "_bm25_search", side_effect=AssertionError("精确条号不应走 BM25")
    ):
        results = retriever.retrieve("请查询民法典第585条", top_k=3, categories=["law"])

    assert len(results) == 1
    assert results[0] == {
        "chunk_id": 11,
        "matched_content": "第五百八十五条 完整第一款。",
        "content": parent_content,
        "source": "中华人民共和国民法典",
        "score": 1.0,
        "source_id": "source-585",
        "trust_status": "authoritative",
        "provenance_type": "official_legal_source",
        "approval_version": 0,
        "article_number": "第五百八十五条",
        "version": "2020",
        "effective_date": "2021-01-01",
        "expiry_date": None,
        "applicability_status": "unknown_as_of",
        "applicability_reason_code": "AS_OF_DATE_UNKNOWN",
        "retrieval_mode": "exact",
        "reliable": True,
        "legal_article_id": 585,
        "chunk_index": 0,
        "chunk_count": 2,
    }


def test_exact_route_prefers_authoritative_parent_over_legacy_chunk(retrieval_db):
    _add_legal_article(retrieval_db, content="第五百八十五条 完整父法条。")
    _add_chunk(
        retrieval_db,
        id=2,
        legal_article_id=None,
        chunk_index=None,
        chunk_count=None,
        content="第五百八十五条 旧记录。",
    )
    _add_chunk(retrieval_db, id=11, content="第五百八十五条 正式切片。")

    result = retriever.retrieve("第585条", top_k=1)[0]

    assert result["chunk_id"] == 11
    assert result["content"] == "第五百八十五条 完整父法条。"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"categories": ["rule"]},
        {"as_of": date(2020, 12, 31)},
        {"as_of": date(2027, 1, 1)},
        {"contract_type": "软件合同", "dimensions": ["breach"]},
        {"contract_type": "采购合同", "dimensions": ["payment"]},
    ],
)
def test_exact_article_route_obeys_all_document_filters(retrieval_db, kwargs):
    _add_legal_article(retrieval_db)
    _add_chunk(
        retrieval_db,
        scope_mode="scoped",
        applicable_contract_types='["采购合同"]',
        applicable_dimensions='["breach"]',
        expiry_date=date(2026, 12, 31),
    )

    assert retriever.retrieve("第585条", **kwargs) == []


def test_natural_language_query_still_uses_bm25_and_vector_rrf(retrieval_db):
    _add_legal_article(retrieval_db)
    _add_chunk(retrieval_db, id=11, embedding="[1.0, 0.0]")
    _add_chunk(
        retrieval_db,
        id=20,
        legal_article_id=None,
        article_number="第五百七十七条",
        content="违约方应当承担违约责任。",
        embedding="[0.0, 1.0]",
    )

    with (
        patch.object(retriever, "_bm25_search", return_value={11: 0, 20: 1}) as bm25,
        patch.object(retriever, "_vector_search", return_value={20: 0, 11: 1}) as vector,
    ):
        results = retriever.retrieve("违约金约定过高时如何调整", top_k=2)

    bm25.assert_called_once()
    vector.assert_called_once()
    assert {item["chunk_id"] for item in results} == {11, 20}
    assert all(item["retrieval_mode"] == "hybrid" for item in results)


def test_top_k_counts_distinct_legal_articles_not_child_chunks(retrieval_db):
    _add_legal_article(retrieval_db)
    _add_chunk(retrieval_db, id=11, chunk_index=0, chunk_count=2)
    _add_chunk(
        retrieval_db,
        id=12,
        content="违约金过高时可以请求适当减少。",
        chunk_index=1,
        chunk_count=2,
    )
    _add_chunk(
        retrieval_db,
        id=20,
        legal_article_id=None,
        article_number="第五百七十七条",
        content="违约方应当承担违约责任。",
    )

    with patch.object(retriever, "_bm25_search", return_value={11: 0, 12: 1, 20: 2}):
        results = retriever.retrieve("违约责任如何承担", top_k=2)

    assert [item["chunk_id"] for item in results] == [11, 20]


def test_many_child_chunks_do_not_exhaust_distinct_article_top_k(retrieval_db):
    _add_legal_article(retrieval_db)
    for offset in range(7):
        _add_chunk(
            retrieval_db,
            id=11 + offset,
            content=f"第五百八十五条 子切片{offset}违约责任。",
            chunk_index=offset,
            chunk_count=7,
        )
    _add_chunk(
        retrieval_db,
        id=30,
        legal_article_id=None,
        article_number="第五百七十七条",
        content="第五百七十七条 另一项违约责任依据。",
    )
    ranks = {**{11 + offset: offset for offset in range(7)}, 30: 7}

    with patch.object(retriever, "_bm25_search", return_value=ranks):
        results = retriever.retrieve("违约责任", top_k=2)

    assert [item["chunk_id"] for item in results] == [11, 30]


def test_embedding_failure_marks_natural_language_result_as_bm25(retrieval_db):
    _add_legal_article(retrieval_db)
    _add_chunk(retrieval_db, id=11, embedding="[1.0, 0.0]")

    with (
        patch.object(retriever, "_bm25_search", return_value={11: 0}),
        patch.object(retriever, "_vector_search", side_effect=LLMError("不可用")),
    ):
        results = retriever.retrieve("违约金约定过高时如何调整")

    assert results[0]["retrieval_mode"] == "bm25"


def test_legacy_chunk_without_parent_remains_retrievable(retrieval_db):
    _add_chunk(
        retrieval_db,
        id=30,
        legal_article_id=None,
        chunk_index=None,
        chunk_count=None,
        content="第五百八十五条 旧知识记录正文。",
    )

    result = retriever.retrieve("第585条", top_k=1)[0]

    assert result["matched_content"] == "第五百八十五条 旧知识记录正文。"
    assert result["content"] == result["matched_content"]
    assert result["legal_article_id"] is None
    assert result["chunk_index"] is None
    assert result["chunk_count"] is None


def test_legacy_chunk_without_article_metadata_uses_content_article_number(retrieval_db):
    _add_chunk(
        retrieval_db,
        id=31,
        legal_article_id=None,
        article_number=None,
        chunk_index=None,
        chunk_count=None,
        content="第五百八十五条 仅正文保留条号。",
    )

    assert retriever.retrieve("第585条", top_k=1)[0]["chunk_id"] == 31
