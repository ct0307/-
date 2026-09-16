from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.models import KnowledgeChunk
from app.services.rag import retriever
from app.services.rag.revision import bump_knowledge_revision


class _EmbeddingAdapter:
    def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]


def _factory(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(retriever, "SessionLocal", factory)
    monkeypatch.setattr(retriever, "get_embedding_adapter", lambda: _EmbeddingAdapter())
    monkeypatch.setattr(retriever.settings, "EMBED_BACKEND", "api")
    monkeypatch.setattr(retriever.settings, "EMBED_MODEL", "snapshot-test")
    monkeypatch.setattr(retriever.settings, "EMBED_DIM", 2)
    retriever._snapshot_store.clear()
    with factory() as db:
        db.add(KnowledgeChunk(
            category="rule",
            source="规则库",
            content="合同付款期限和验收条件应当明确。",
            embedding="[1.0, 0.0]",
            embedding_model="snapshot-test",
            embedding_dimension=2,
            scope_mode="global",
        ))
        db.commit()
    return engine, factory


def test_same_revision_reuses_rows_bm25_and_parsed_vectors(monkeypatch):
    engine, _factory_value = _factory(monkeypatch)
    original_loader = retriever._load_docs_from_session
    original_parser = retriever._parse_stored_vector
    try:
        with (
            patch.object(retriever, "_load_docs_from_session", wraps=original_loader) as loader,
            patch.object(retriever, "_parse_stored_vector", wraps=original_parser) as parser,
        ):
            results = [retriever.retrieve("付款期限", top_k=1) for _ in range(10)]

        assert all(result and result[0]["chunk_id"] for result in results)
        assert loader.call_count == 1
        assert parser.call_count == 1
    finally:
        retriever._snapshot_store.clear()
        engine.dispose()


def test_revision_change_rebuilds_snapshot_once(monkeypatch):
    engine, factory = _factory(monkeypatch)
    original_loader = retriever._load_docs_from_session
    try:
        with patch.object(
            retriever, "_load_docs_from_session", wraps=original_loader
        ) as loader:
            retriever.retrieve("付款期限", top_k=1)
            with factory() as db:
                db.add(KnowledgeChunk(
                    category="rule",
                    source="补充规则",
                    content="逾期付款应承担违约责任。",
                    embedding="[1.0, 0.0]",
                    embedding_model="snapshot-test",
                    embedding_dimension=2,
                    scope_mode="global",
                ))
                bump_knowledge_revision(db)
                db.commit()
            retriever.retrieve("付款期限", top_k=2)
            retriever.retrieve("付款期限", top_k=2)

        assert loader.call_count == 2
    finally:
        retriever._snapshot_store.clear()
        engine.dispose()


def test_snapshot_and_forced_uncached_results_are_identical(monkeypatch):
    engine, _factory_value = _factory(monkeypatch)
    try:
        cached = retriever.retrieve("付款期限", top_k=1)
        with patch.object(
            retriever._snapshot_store,
            "get",
            side_effect=RuntimeError("force uncached"),
        ):
            uncached = retriever.retrieve("付款期限", top_k=1)

        assert uncached == cached
    finally:
        retriever._snapshot_store.clear()
        engine.dispose()
