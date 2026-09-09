from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.models import KnowledgeChunk, LegalArticle
from app.llm.base import LLMError
from app.services.rag import retriever
from app.services.rag.legal_import import (
    apply_legal_import,
    LegalImportError,
    preview_legal_import,
    verify_preview_token,
)
from app.api.v1.endpoints import knowledge


RESOURCES = Path(__file__).parents[1] / "resources" / "legal_sources"
OFFICIAL_FILE = RESOURCES / "civil-code.txt"


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


def test_preview_accepts_complete_official_civil_code_without_writing(db):
    raw = OFFICIAL_FILE.read_bytes()
    before = (db.query(LegalArticle).count(), db.query(KnowledgeChunk).count())

    preview = preview_legal_import(
        db,
        filename=OFFICIAL_FILE.name,
        raw_content=raw,
        extracted_text=raw.decode("utf-8"),
        user_id=7,
    )

    assert preview.allowed is True
    assert preview.source_id == "civil-code-2020"
    assert preview.article_count == 1260
    assert preview.chunk_count >= 1260
    assert preview.hash_matches is True
    assert preview.errors == ()
    assert preview.token
    assert (db.query(LegalArticle).count(), db.query(KnowledgeChunk).count()) == before


def test_preview_rejects_missing_article_and_hash_mismatch(db):
    raw = OFFICIAL_FILE.read_bytes()
    text = raw.decode("utf-8")
    truncated = text[: text.rfind("第一千二百六十条")].encode("utf-8")

    preview = preview_legal_import(
        db,
        filename="中华人民共和国民法典.txt",
        raw_content=truncated,
        extracted_text=truncated.decode("utf-8"),
        user_id=7,
    )

    assert preview.allowed is False
    assert preview.hash_matches is False
    assert preview.token is None
    assert any("缺少条号" in error or "条数" in error for error in preview.errors)


def test_preview_rejects_complete_but_modified_file(db):
    raw = OFFICIAL_FILE.read_bytes()
    modified = raw + b"\n"

    preview = preview_legal_import(
        db,
        filename="中华人民共和国民法典.txt",
        raw_content=modified,
        extracted_text=modified.decode("utf-8"),
        user_id=7,
    )

    assert preview.article_count == 1260
    assert preview.hash_matches is False
    assert preview.allowed is False
    assert preview.token is None
    assert "文件哈希与官方基准不一致" in preview.errors


def test_preview_token_binds_file_user_and_expiry(db):
    raw = OFFICIAL_FILE.read_bytes()
    preview = preview_legal_import(
        db,
        filename="中华人民共和国民法典.txt",
        raw_content=raw,
        extracted_text=raw.decode("utf-8"),
        user_id=7,
    )

    payload = verify_preview_token(preview.token, raw_content=raw, user_id=7)
    assert payload["source_id"] == "civil-code-2020"

    with pytest.raises(LegalImportError, match="预检令牌"):
        verify_preview_token(preview.token + "x", raw_content=raw, user_id=7)
    with pytest.raises(LegalImportError, match="用户"):
        verify_preview_token(preview.token, raw_content=raw, user_id=8)
    with pytest.raises(LegalImportError, match="文件"):
        verify_preview_token(preview.token, raw_content=raw + b"x", user_id=7)
    with pytest.raises(LegalImportError, match="过期"):
        verify_preview_token(
            preview.token,
            raw_content=raw,
            user_id=7,
            now=datetime.now(timezone.utc) + timedelta(minutes=11),
        )


class RecordingEmbeddingAdapter:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.inputs: list[list[str]] = []

    def embed(self, texts):
        self.inputs.append(list(texts))
        if self.fail:
            raise LLMError("测试向量服务不可用")
        return [[1.0, 0.0] for _ in texts]


def _official_preview(db, user_id=7):
    raw = OFFICIAL_FILE.read_bytes()
    return raw, preview_legal_import(
        db,
        filename="中华人民共和国民法典.txt",
        raw_content=raw,
        extracted_text=raw.decode("utf-8"),
        user_id=user_id,
    )


def test_apply_imports_complete_parent_child_knowledge_atomically(db, monkeypatch):
    raw, preview = _official_preview(db)
    adapter = RecordingEmbeddingAdapter()
    monkeypatch.setattr(retriever, "get_embedding_adapter", lambda: adapter)
    monkeypatch.setattr(retriever.settings, "EMBED_DIM", 2)

    result = apply_legal_import(
        db,
        filename="中华人民共和国民法典.txt",
        raw_content=raw,
        extracted_text=raw.decode("utf-8"),
        token=preview.token,
        user_id=7,
    )

    assert result.article_count == 1260
    assert result.chunk_count >= 1260
    assert result.first_article_ok is True
    assert result.article_585_ok is True
    assert result.last_article_ok is True
    assert db.query(LegalArticle).filter_by(source_id="civil-code-2020").count() == 1260
    assert db.query(KnowledgeChunk).filter(
        KnowledgeChunk.legal_article_id.isnot(None)
    ).count() == result.chunk_count


def test_repeated_apply_reuses_embeddings_without_growing_rows(db, monkeypatch):
    raw, preview = _official_preview(db)
    adapter = RecordingEmbeddingAdapter()
    monkeypatch.setattr(retriever, "get_embedding_adapter", lambda: adapter)
    monkeypatch.setattr(retriever.settings, "EMBED_DIM", 2)
    first = apply_legal_import(
        db, filename="民法典.txt", raw_content=raw, extracted_text=raw.decode(),
        token=preview.token, user_id=7,
    )
    _, second_preview = _official_preview(db)
    adapter.inputs.clear()

    second = apply_legal_import(
        db, filename="民法典.txt", raw_content=raw, extracted_text=raw.decode(),
        token=second_preview.token, user_id=7,
    )

    assert second.reused_embeddings == first.chunk_count
    assert second.rebuilt_embeddings == 0
    assert adapter.inputs == []
    assert db.query(LegalArticle).filter_by(source_id="civil-code-2020").count() == 1260


def test_embedding_failure_preserves_existing_civil_code(db, monkeypatch):
    raw, preview = _official_preview(db)
    monkeypatch.setattr(
        retriever, "get_embedding_adapter", lambda: RecordingEmbeddingAdapter()
    )
    monkeypatch.setattr(retriever.settings, "EMBED_DIM", 2)
    apply_legal_import(
        db, filename="民法典.txt", raw_content=raw, extracted_text=raw.decode(),
        token=preview.token, user_id=7,
    )
    before = db.query(LegalArticle.content_hash).filter_by(
        source_id="civil-code-2020"
    ).order_by(LegalArticle.id).all()
    _, retry_preview = _official_preview(db)
    monkeypatch.setattr(
        retriever, "get_embedding_adapter", lambda: RecordingEmbeddingAdapter(fail=True)
    )
    monkeypatch.setattr(retriever.settings, "EMBED_DIM", 3)

    with pytest.raises(LLMError, match="测试向量服务不可用"):
        apply_legal_import(
            db, filename="民法典.txt", raw_content=raw, extracted_text=raw.decode(),
            token=retry_preview.token, user_id=7,
        )

    assert db.query(LegalArticle.content_hash).filter_by(
        source_id="civil-code-2020"
    ).order_by(LegalArticle.id).all() == before


def test_router_exposes_authoritative_preview_and_apply_endpoints():
    routes = {(route.path, tuple(route.methods or ())) for route in knowledge.router.routes}

    assert ("/legal-import/preview", ("POST",)) in routes
    assert ("/legal-import/apply", ("POST",)) in routes
