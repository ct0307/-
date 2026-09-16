import asyncio
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints import knowledge
from app.db.session import Base
from app.models.models import KnowledgeChunk
from app.schemas.contract import KnowledgeImport
from app.services.rag.revision import (
    bump_knowledge_revision,
    current_knowledge_revision,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_revision_starts_at_zero_and_bump_is_transactional(db):
    assert current_knowledge_revision(db) == 0
    db.add(KnowledgeChunk(category="law", source="test", content="原文"))
    assert bump_knowledge_revision(db) == 1
    db.commit()
    assert current_knowledge_revision(db) == 1


def test_rollback_does_not_publish_revision(db):
    assert current_knowledge_revision(db) == 0
    db.add(KnowledgeChunk(category="law", source="test", content="待回滚"))
    bump_knowledge_revision(db)
    db.rollback()
    assert current_knowledge_revision(db) == 0
    assert db.query(KnowledgeChunk).count() == 0


def test_each_explicit_bump_increments_once(db):
    assert bump_knowledge_revision(db) == 1
    assert bump_knowledge_revision(db) == 2
    db.commit()
    assert current_knowledge_revision(db) == 2


def _install_endpoint_fakes(monkeypatch):
    def fake_index(chunks, db):
        for row in knowledge.build_documents_without_embeddings(chunks):
            db.add(row)
        db.flush()
        return len(chunks)

    def fake_prepare(chunks):
        return knowledge.build_documents_without_embeddings(chunks)

    monkeypatch.setattr(knowledge, "_do_index", fake_index)
    monkeypatch.setattr(knowledge, "prepare_documents", fake_prepare)
    monkeypatch.setattr(knowledge.audit_log, "record", lambda *_args, **_kwargs: None)


def test_manual_import_bumps_revision_once(db, monkeypatch):
    _install_endpoint_fakes(monkeypatch)
    before = current_knowledge_revision(db)

    knowledge.import_knowledge(
        KnowledgeImport(
            category="rule",
            source="manual",
            content="这是用于验证知识库修订号递增的完整风险规则文本。",
        ),
        db=db,
        user=SimpleNamespace(id=1),
    )

    assert current_knowledge_revision(db) == before + 1


def test_file_import_and_source_replace_each_bump_once(db, monkeypatch):
    _install_endpoint_fakes(monkeypatch)
    user = SimpleNamespace(id=1)
    source = "rules.txt"

    asyncio.run(knowledge.import_knowledge_file(
        file=UploadFile(
            filename=source,
            file=BytesIO("第一版知识规则内容足够长，用于验证批量文件导入修订号。".encode()),
        ),
        category="rule",
        overwrite=False,
        scope_mode="global",
        applicable_contract_types="[]",
        applicable_dimensions="[]",
        db=db,
        user=user,
    ))
    assert current_knowledge_revision(db) == 1

    asyncio.run(knowledge.import_knowledge_file(
        file=UploadFile(
            filename=source,
            file=BytesIO("第二版知识规则内容足够长，用于验证按来源替换修订号。".encode()),
        ),
        category="rule",
        overwrite=True,
        scope_mode="global",
        applicable_contract_types="[]",
        applicable_dimensions="[]",
        db=db,
        user=user,
    ))
    assert current_knowledge_revision(db) == 2
    assert db.query(KnowledgeChunk).filter_by(source=source).count() == 1


def test_delete_chunk_bumps_revision_once(db):
    chunk = KnowledgeChunk(category="rule", source="delete", content="待删除知识", embedding="")
    db.add(chunk)
    db.commit()
    before = current_knowledge_revision(db)

    knowledge.delete_knowledge(
        chunk_id=chunk.id,
        db=db,
        user=SimpleNamespace(id=1),
    )

    assert current_knowledge_revision(db) == before + 1
    assert db.get(KnowledgeChunk, chunk.id) is None
