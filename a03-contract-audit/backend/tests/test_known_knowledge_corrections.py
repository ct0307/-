"""已知错误只做精确纠错，预览无写入、重复执行无副作用。"""
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.models import KnowledgeChunk, AuditLog, User
from app.services.rag.known_corrections import correction_catalog, correct_known_rules
from app.services.rag.revision import current_knowledge_revision


def test_preview_apply_and_repeat_keep_trust_conservative():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(username='admin', password_hash='x', role='admin')
        db.add(user); db.flush()
        catalog = correction_catalog()
        rows = [KnowledgeChunk(category='rule', source=item['source'], content=item['before'],
                               trust_status='approved_internal', approved_content_hash='old', embedding='[1,2]')
                for item in catalog]
        untouched = KnowledgeChunk(category='rule', source=catalog[0]['source'], content=catalog[0]['before'] + '人工补充。')
        db.add_all([*rows, untouched]); db.commit()
        preview = correct_known_rules(db, user, apply=False)
        assert len(preview) == 2
        db.expire_all()
        assert rows[0].content == catalog[0]['before']
        assert current_knowledge_revision(db) == 0
        assert db.query(AuditLog).count() == 0
        assert len(correct_known_rules(db, user, apply=True)) == 2
        assert [row.content for row in rows] == [item['after'] for item in catalog]
        assert all(row.trust_status == 'unverified' and row.approved_content_hash == '' for row in rows)
        assert all(row.embedding == '' and row.embedding_signature is None for row in rows)
        assert untouched.content.endswith('人工补充。')
        assert current_knowledge_revision(db) == 1
        logs = db.query(AuditLog).filter_by(action='correct_knowledge').all()
        assert len(logs) == 2
        assert json.loads(logs[0].detail)['before'] == catalog[0]['before']
        assert correct_known_rules(db, user, apply=True) == []
        assert current_knowledge_revision(db) == 1
        assert db.query(AuditLog).count() == 2
    engine.dispose()


def test_only_admin_can_apply_or_preview():
    with pytest.raises(HTTPException) as caught:
        correct_known_rules(None, SimpleNamespace(role='legal'), apply=True)
    assert caught.value.status_code == 403
