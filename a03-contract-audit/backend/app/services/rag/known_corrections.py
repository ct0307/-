"""已知旧知识条目的精确纠错，不将修订自动视为专业核验。"""
import hashlib
import json
from pathlib import Path

from fastapi import HTTPException
from app.models.models import KnowledgeChunk
from app.services import audit_log
from app.services.rag.revision import bump_knowledge_revision


def correction_catalog() -> list[dict[str, str]]:
    path = Path(__file__).resolve().parents[3] / 'resources' / 'known-rule-corrections.json'
    return json.loads(path.read_text(encoding='utf-8'))


def correct_known_rules(db, user, *, apply: bool = False) -> list[dict]:
    if user.role != 'admin':
        raise HTTPException(403, '仅管理员可执行已知知识纠错')
    changes = []
    for item in correction_catalog():
        rows = db.query(KnowledgeChunk).filter_by(
            source=item['source'], category='rule', content=item['before'], legal_article_id=None,
        ).all()
        for row in rows:
            change = dict(id=row.id, **item)
            changes.append(change)
            if not apply:
                continue
            changed = db.query(KnowledgeChunk).filter_by(
                id=row.id, content=item['before'], approval_version=row.approval_version,
            ).update(dict(
                content=item['after'], trust_status='unverified', approved_by=None, approved_at=None,
                approved_content_hash='', approval_version=row.approval_version + 1,
                embedding='', embedding_model=None, embedding_dimension=None, embedding_signature=None,
                content_hash=hashlib.sha256(item['after'].encode('utf-8')).hexdigest(), retrieval_text=None,
            ), synchronize_session='fetch')
            if changed != 1:
                db.rollback()
                raise HTTPException(409, '知识内容已变化，请重新预览后执行纠错')
            audit_log.record(db, user_id=user.id, action='correct_knowledge',
                             target=f'knowledge:{row.id}', detail=json.dumps(change, ensure_ascii=False))
    if apply and changes:
        bump_knowledge_revision(db)
        db.commit()
    return changes
