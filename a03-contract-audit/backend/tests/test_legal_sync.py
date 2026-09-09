import json
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.llm.base import LLMError
from app.models.models import KnowledgeChunk, LegalArticle, LegalSource
from app.services.rag import retriever
from app.services.rag.legal_sync import apply_legal_sync, plan_legal_sync


class FakeEmbeddingAdapter:
    def __init__(self, vectors):
        self.vectors = vectors
        self.inputs = []

    def embed(self, texts):
        self.inputs.append(list(texts))
        return self.vectors


class DynamicEmbeddingAdapter:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.inputs = []

    def embed(self, texts):
        self.inputs.append(list(texts))
        if self.fail:
            raise LLMError("测试向量服务不可用")
        return [[1.0, 0.0] for _ in texts]


def _legal_chunk(**overrides):
    chunk = {
        "category": "law",
        "source": "中华人民共和国民法典",
        "content": "第五百一十一条 第一款正文。",
        "retrieval_text": "中华人民共和国民法典 第三编 合同 第五百一十一条 第一款正文。",
        "article_number": "第五百一十一条",
        "chunk_index": 0,
        "chunk_count": 1,
        "chunk_schema_version": "legal-v1",
        "scope_mode": "global",
    }
    return {**chunk, **overrides}


MANIFEST = Path(__file__).parent / "fixtures" / "legal_sources" / "manifest.json"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_embedding_signature_is_stable_and_version_sensitive():
    base = retriever.embedding_signature(
        backend="local",
        model="bge-test",
        dimension=2,
        normalization="l2",
        chunk_schema_version="legal-v1",
    )

    assert base == retriever.embedding_signature(
        backend="local",
        model="bge-test",
        dimension=2,
        normalization="l2",
        chunk_schema_version="legal-v1",
    )
    assert base != retriever.embedding_signature(
        backend="local",
        model="bge-test",
        dimension=2,
        normalization="l2",
        chunk_schema_version="legal-v2",
    )


def test_legal_embedding_uses_retrieval_text_and_records_signature():
    adapter = FakeEmbeddingAdapter([[1.0, 0.0]])
    with (
        patch.object(retriever, "get_embedding_adapter", return_value=adapter),
        patch.object(retriever.settings, "EMBED_DIM", 2),
    ):
        row = retriever.prepare_documents([_legal_chunk()])[0]

    assert adapter.inputs == [[_legal_chunk()["retrieval_text"]]]
    assert row.retrieval_text == _legal_chunk()["retrieval_text"]
    assert row.embedding_signature
    assert row.chunk_schema_version == "legal-v1"
    assert row.chunk_index == 0
    assert row.chunk_count == 1


@pytest.mark.parametrize(
    "vectors",
    [[], [[float("nan"), 0.0]], [[float("inf"), 0.0]], [[1.0]], [[1.0, 0.0, 0.0]]],
)
def test_legal_embedding_rejects_invalid_count_values_and_dimension(vectors):
    with (
        patch.object(
            retriever, "get_embedding_adapter", return_value=FakeEmbeddingAdapter(vectors)
        ),
        patch.object(retriever.settings, "EMBED_DIM", 2),
    ):
        with pytest.raises(LLMError):
            retriever.prepare_documents([_legal_chunk()])


def test_matching_retrieval_hash_and_signature_reuses_embedding():
    first_adapter = FakeEmbeddingAdapter([[0.6, 0.8]])
    with (
        patch.object(retriever, "get_embedding_adapter", return_value=first_adapter),
        patch.object(retriever.settings, "EMBED_DIM", 2),
    ):
        first = retriever.prepare_documents([_legal_chunk()])[0]
    cache = {
        (first.content_hash, first.embedding_signature): json.loads(first.embedding)
    }
    unused_adapter = FakeEmbeddingAdapter([])

    with (
        patch.object(retriever, "get_embedding_adapter", return_value=unused_adapter),
        patch.object(retriever.settings, "EMBED_DIM", 2),
    ):
        reused = retriever.prepare_documents([_legal_chunk()], embedding_cache=cache)[0]

    assert unused_adapter.inputs == []
    assert reused.embedding == first.embedding


def test_changed_retrieval_text_rebuilds_embedding():
    adapter = FakeEmbeddingAdapter([[0.0, 1.0]])
    with (
        patch.object(retriever, "get_embedding_adapter", return_value=adapter),
        patch.object(retriever.settings, "EMBED_DIM", 2),
    ):
        row = retriever.prepare_documents(
            [_legal_chunk(retrieval_text="修改后的检索文本")],
            embedding_cache={("unrelated", "signature"): [1.0, 0.0]},
        )[0]

    assert adapter.inputs == [["修改后的检索文本"]]
    assert json.loads(row.embedding) == [0.0, 1.0]


def test_sync_plan_is_read_only_and_reports_target_counts(db):
    adapter = DynamicEmbeddingAdapter()
    with patch.object(retriever, "get_embedding_adapter", return_value=adapter):
        report = plan_legal_sync(db, MANIFEST)

    assert report.source_count == 1
    assert report.article_count == 3
    assert report.chunk_count == 3
    assert report.rebuild_embedding_count == 3
    assert adapter.inputs == []
    assert db.query(LegalSource).count() == 0


def test_sync_plan_supports_pre_migration_database():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE knowledge_chunks ("
            "id INTEGER PRIMARY KEY, category VARCHAR(32), source VARCHAR(255), "
            "content TEXT, embedding TEXT)"
        ))
        connection.execute(text(
            "INSERT INTO knowledge_chunks "
            "(category, source, content, embedding) VALUES "
            "('law', '民法典-合同编.txt', '旧合同编', '')"
        ))
    session = sessionmaker(bind=engine)()
    try:
        report = plan_legal_sync(session, MANIFEST, replace_legacy=True)
    finally:
        session.close()
        engine.dispose()

    assert report.article_count == 3
    assert report.reuse_embedding_count == 0
    assert report.rebuild_embedding_count == 3
    assert report.replace_chunk_count == 1


def test_first_and_repeated_sync_are_idempotent(db):
    adapter = DynamicEmbeddingAdapter()
    with (
        patch.object(retriever, "get_embedding_adapter", return_value=adapter),
        patch.object(retriever.settings, "EMBED_DIM", 2),
    ):
        first = apply_legal_sync(db, MANIFEST)
        second = apply_legal_sync(db, MANIFEST)

    assert first.article_count == second.article_count == 3
    assert db.query(LegalSource).count() == 1
    assert db.query(LegalArticle).count() == 3
    assert db.query(KnowledgeChunk).filter(KnowledgeChunk.category == "law").count() == 3
    assert second.reuse_embedding_count == 3


def test_embedding_failure_keeps_existing_legal_knowledge(db):
    with (
        patch.object(
            retriever, "get_embedding_adapter", return_value=DynamicEmbeddingAdapter()
        ),
        patch.object(retriever.settings, "EMBED_DIM", 2),
    ):
        apply_legal_sync(db, MANIFEST)
    before = [row.content for row in db.query(KnowledgeChunk).order_by(KnowledgeChunk.id)]

    with (
        patch.object(
            retriever,
            "get_embedding_adapter",
            return_value=DynamicEmbeddingAdapter(fail=True),
        ),
        patch.object(retriever.settings, "EMBED_DIM", 3),
    ):
        with pytest.raises(LLMError, match="测试向量服务不可用"):
            apply_legal_sync(db, MANIFEST)

    assert [row.content for row in db.query(KnowledgeChunk).order_by(KnowledgeChunk.id)] == before


def test_sync_preserves_uncontrolled_knowledge_and_requires_legacy_flag(db):
    db.add_all([
        KnowledgeChunk(category="rule", source="人工规则", content="保留规则", embedding=""),
        KnowledgeChunk(
            category="law", source="民法典-合同编.txt", content="旧合同编", embedding=""
        ),
    ])
    db.commit()

    with (
        patch.object(
            retriever, "get_embedding_adapter", return_value=DynamicEmbeddingAdapter()
        ),
        patch.object(retriever.settings, "EMBED_DIM", 2),
    ):
        apply_legal_sync(db, MANIFEST, replace_legacy=False)
        assert db.query(KnowledgeChunk).filter_by(source="民法典-合同编.txt").count() == 1
        apply_legal_sync(db, MANIFEST, replace_legacy=True)

    assert db.query(KnowledgeChunk).filter_by(source="民法典-合同编.txt").count() == 0
    assert db.query(KnowledgeChunk).filter_by(source="人工规则").count() == 1
