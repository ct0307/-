"""知识库写入修订号：与知识库变更共用同一数据库事务。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import KnowledgeIndexState


def current_knowledge_revision(db: Session) -> int:
    """只读当前修订号；测试库或旧库缺少单例行时视为 0。"""
    revision = db.execute(
        select(KnowledgeIndexState.revision).where(KnowledgeIndexState.id == 1)
    ).scalar_one_or_none()
    return int(revision or 0)


def bump_knowledge_revision(db: Session) -> int:
    """在当前事务中递增修订号，调用方负责最终 commit/rollback。"""
    row = db.execute(
        select(KnowledgeIndexState)
        .where(KnowledgeIndexState.id == 1)
        .with_for_update()
    ).scalar_one_or_none()
    if row is None:
        row = KnowledgeIndexState(id=1, revision=0)
        db.add(row)
        db.flush()
    row.revision = int(row.revision) + 1
    db.flush()
    return int(row.revision)
