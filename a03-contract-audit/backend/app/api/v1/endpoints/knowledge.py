"""知识库端点：导入法规/行业规则/合同模板，切片向量化供 RAG 检索。"""
import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.session import get_db
from app.llm.base import LLMError
from app.models.models import User
from app.schemas.contract import KnowledgeImport
from app.services import audit_log
from app.services.rag.retriever import index_documents

router = APIRouter()

# 切片长度上限（字符）：过长段落再按句号切，兼顾 embedding 质量与检索粒度。
_MAX_CHUNK_CHARS = 500


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
