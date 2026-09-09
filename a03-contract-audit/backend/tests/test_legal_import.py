from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.models import KnowledgeChunk, LegalArticle
from app.services.rag.legal_import import (
    LegalImportError,
    preview_legal_import,
    verify_preview_token,
)


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
        filename="中华人民共和国民法典.txt",
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
