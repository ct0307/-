"""知识库端点：导入法规/行业规则/合同模板，切片向量化供 RAG 检索；查询卡片/统计。"""
import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.llm.base import LLMError
from app.models.models import KnowledgeChunk, User
from app.schemas.contract import KnowledgeImport
from app.services import audit_log
from app.services.rag.retriever import index_documents

router = APIRouter()

# 切片长度上限（字符）：过长段落再按句号切，兼顾 embedding 质量与检索粒度。
_MAX_CHUNK_CHARS = 500

# 知识库 category（存英文）→ 前端展示四类中文。与 seed 写入口径一致。
_CAT_LABEL = {
    "law": "法律法规",
    "template": "标准条款",
    "rule": "风险规则",
    "case": "典型案例",
}
# 卡片摘要截断长度
_DESC_MAX = 120


def _split_chunks(text: str) -> list[str]:
    """按空行分段，过长段落再按中文句号切，去空白。"""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    for para in paragraphs:
        if len(para) <= _MAX_CHUNK_CHARS:
            chunks.append(para)
            continue
        buf = ""
        for sent in re.split(r"(?<=[。；;])", para):
            if len(buf) + len(sent) > _MAX_CHUNK_CHARS and buf:
                chunks.append(buf)
                buf = ""
            buf += sent
        if buf.strip():
            chunks.append(buf.strip())
    return chunks


@router.post("/import")
def import_knowledge(
    payload: KnowledgeImport,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("legal", "admin")),
) -> dict:
    pieces = _split_chunks(payload.content)
    if not pieces:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "内容为空，无可导入切片")

    chunks = [{"category": payload.category, "source": payload.source, "content": p} for p in pieces]
    try:
        count = index_documents(chunks, db=db)
    except LLMError as exc:
        # embedding 服务不可用：明确报错，不静默写入空向量
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"向量化服务不可用：{exc}") from exc

    audit_log.record(db, user_id=user.id, action="import_knowledge", target=payload.category, detail=f"chunks={count}")
    return {"category": payload.category, "source": payload.source, "imported_chunks": count}


def _chips_for(cat_label: str, source: str) -> list[str]:
    """卡片标签：分类中文 + 来源关键片段。"""
    chips = [cat_label]
    # 从来源名里取书名号内内容或末段作为第二个 chip
    m = re.search(r"《([^》]+)》", source)
    if m:
        chips.append(m.group(1))
    return chips[:3]


@router.get("/cards")
def knowledge_cards(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """知识库卡片列表，形状对齐前端 KnowledgeCard（id/title/cat/desc/chips/date）。"""
    rows = db.query(KnowledgeChunk).order_by(KnowledgeChunk.created_at.desc()).all()
    cards: list[dict] = []
    for c in rows:
        cat_label = _CAT_LABEL.get(c.category, "风险规则")
        desc = c.content if len(c.content) <= _DESC_MAX else c.content[:_DESC_MAX] + "…"
        cards.append({
            "id": f"K{c.id:02d}",
            "title": c.source or c.content[:20],
            "cat": cat_label,
            "desc": desc,
            "chips": _chips_for(cat_label, c.source),
            "date": c.created_at.strftime("%Y-%m-%d") if c.created_at else "",
        })
    return cards


@router.get("/stats")
def knowledge_stats(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """知识库分类统计，形状对齐前端 KNOWLEDGE_STATS（cat/count）。四类恒定展示。"""
    rows = dict(db.query(KnowledgeChunk.category, func.count(KnowledgeChunk.id)).group_by(KnowledgeChunk.category).all())
    # 四类固定顺序输出，无数据补 0，保证前端四张统计卡不塌
    order = ["law", "template", "rule", "case"]
    return [{"cat": _CAT_LABEL[k], "count": rows.get(k, 0)} for k in order]
