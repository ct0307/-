from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints import knowledge
from app.db.session import Base
from app.models.models import KnowledgeChunk
from app.services.rag.retriever import _load_docs_from_session, _result_from_doc
from app.services.rag.revision import current_knowledge_revision


def test_approval_revoke_and_content_change_invalidate_trust(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(knowledge.audit_log, "record", lambda *a, **k: None)
    with Session(engine) as db:
        row = KnowledgeChunk(content="付款须经财务审批", source="企业规则", category="rule", scope_mode="global")
        db.add(row)
        db.commit()
        user = SimpleNamespace(id=1, role="admin")
        payload = knowledge.KnowledgeApproval(status="approved_internal", reason="已核对制度原文", expected_version=0)
        knowledge.approve_knowledge(row.id, payload, db, user)
        assert current_knowledge_revision(db) == 1
        result = lambda: _result_from_doc(_load_docs_from_session(db)[0], score=1, retrieval_mode="test")
        assert result()["reliable"] is True
        with pytest.raises(HTTPException) as caught:
            knowledge.approve_knowledge(row.id, payload, db, user)
        assert caught.value.status_code == 409
        row.content = "未经审批的新规则"
        db.commit()
        assert result()["reliable"] is False
        knowledge.approve_knowledge(row.id, knowledge.KnowledgeApproval(status="rejected", reason="内容已修改", expected_version=1), db, user)
        assert result()["reliable"] is False
        assert current_knowledge_revision(db) == 2


def test_non_admin_cannot_approve_even_via_service_entry():
    with pytest.raises(HTTPException) as caught:
        knowledge.approve_knowledge(1, knowledge.KnowledgeApproval(status="approved_internal", reason="尝试审批", expected_version=0), None, SimpleNamespace(role="legal"))
    assert caught.value.status_code == 403
