"""知识库端点：导入法规/行业规则/合同模板，切片向量化供 RAG 检索；查询卡片/统计。"""
import io
import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
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


# —— 工具函数 ——

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


async def _extract_file_text(file: UploadFile) -> str:
    """从上传文件提取纯文本。支持 txt / docx / pdf。"""
    raw = await file.read()
    fname = (file.filename or "").lower()

    if fname.endswith(".txt"):
        for enc in ("utf-8", "gbk", "utf-8-sig"):
            try:
                return raw.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return raw.decode("utf-8", errors="replace")

    if fname.endswith(".docx"):
        try:
            from docx import Document  # python-docx
            doc = Document(io.BytesIO(raw))
            return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"docx 解析失败：{exc}") from exc

    if fname.endswith(".pdf"):
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(raw)) as pdf:
                pages = [p.extract_text() or "" for p in pdf.pages]
            return "\n\n".join(t for t in pages if t.strip())
        except Exception as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"pdf 解析失败：{exc}") from exc

    raise HTTPException(
        status.HTTP_400_BAD_REQUEST,
        "不支持的文件类型，仅支持 .txt / .docx / .pdf",
    )


def _do_index(chunks: list[dict], db: Session) -> int:
    """切片向量化入库，embedding 不可用时降级写空向量。"""
    try:
        return index_documents(chunks, db=db)
    except LLMError:
        for c in chunks:
            db.add(KnowledgeChunk(
                category=c["category"], source=c["source"],
                content=c["content"], embedding="",
            ))
        db.commit()
        return len(chunks)


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
    except LLMError:
        # embedding 服务不可用（如 DeepSeek 无 /embeddings 端点）：
        # 降级写入空向量，RAG 走关键词检索——与 seed 演示数据保持一致。
        from app.models.models import KnowledgeChunk
        for c in chunks:
            db.add(KnowledgeChunk(
                category=c["category"], source=c["source"],
                content=c["content"], embedding="",
            ))
        db.commit()
        count = len(chunks)

    audit_log.record(db, user_id=user.id, action="import_knowledge", target=payload.category, detail=f"chunks={count}")
    return {"category": payload.category, "source": payload.source, "imported_chunks": count}


@router.post("/import-file")
async def import_knowledge_file(
    file: UploadFile = File(...),
    category: str = Form("law"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("legal", "admin")),
) -> dict:
    """上传文件批量导入知识库。支持 .txt / .docx / .pdf。

    文件内容按段落自动切片（每片 ≤500字），逐片向量化入库。
    同一文件名可重复导入（用于内容更新），不做去重（由调用方控制）。
    """
    content = await _extract_file_text(file)
    pieces = _split_chunks(content)
    if not pieces:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "文件内容为空或无法提取文本")

    source = file.filename or "未命名文件"
    chunks = [{"category": category, "source": source, "content": p} for p in pieces]
    count = _do_index(chunks, db)

    audit_log.record(
        db, user_id=user.id,
        action="import_knowledge_file",
        target=source,
        detail=f"category={category} chunks={count}",
    )
    return {"source": source, "category": category, "imported_chunks": count}


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
