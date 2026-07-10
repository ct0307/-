"""知识库端点：导入法规/行业规则/合同模板，切片向量化供 RAG 检索；查询卡片/统计。"""
import hashlib
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
# 切片长度下限（字符）：短于此的碎片视为噪音丢弃（页码、孤立标点等）。
_MIN_CHUNK_CHARS = 8

# 法条条文起始标记：「第X条」，X 支持中文数字或阿拉伯数字。
# 用于识别法规文本并按条文边界切割，保留单条法条的完整语义。
# 行首锚定（MULTILINE + ^\s*）：只把「行首」的第X条当条文边界，
# 避免正文里的交叉引用（如「依照本法第五百零九条规定」）被误判为新条文起点。
_ARTICLE_RE = re.compile(r"^[\t 　]*第[一二三四五六七八九十百千零两\d]{1,7}条", re.MULTILINE)

# 纯噪音行判定：页码（- 3 -/第3页/共10页/3/25）、纯符号、单字等。
_NOISE_LINE_RE = re.compile(
    r"^(?:[-—\s]*第?\s*\d+\s*[页/-]?\s*(?:页|共\s*\d+\s*页)?[-—\s]*|\d+\s*/\s*\d+|[\s\W_]+)$"
)

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

def _clean_lines(text: str) -> str:
    """去除噪音行（页码、纯符号），保留空行作为段落分隔。

    空行是段落边界（供后续 _split_paragraph 分段），不能删；
    只删非空但属噪音的行（页码、纯符号等）。
    """
    out: list[str] = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            out.append("")  # 保留空行，维持段落结构
        elif not _NOISE_LINE_RE.match(s):
            out.append(ln)
        # 噪音行：丢弃
    return "\n".join(out)


def _split_by_article(text: str) -> list[str] | None:
    """尝试按「第X条」条文边界切割。若文本中 ≥2 条命中，返回切割结果；否则返回 None（降级）。"""
    # 找出所有条文起始位置
    matches = list(_ARTICLE_RE.finditer(text))
    if len(matches) < 2:
        return None
    # 按条文边界切：从每个「第X条」开始到下一个「第X条」前结束
    articles: list[str] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        if chunk:
            articles.append(chunk)
    return articles


def _split_paragraph(text: str) -> list[str]:
    """通用段落切割：空行分段 → 超长按中文句号切。"""
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


class SplitResult:
    """智能切片结果，携带模式元信息供前端展示。"""
    __slots__ = ("chunks", "mode", "article_count", "paragraph_count")

    def __init__(self, chunks: list[str], mode: str, article_count: int, paragraph_count: int):
        self.chunks = chunks
        self.mode = mode
        self.article_count = article_count
        self.paragraph_count = paragraph_count


def _smart_split(text: str) -> SplitResult:
    """智能切片：法条识别优先 → 降级段落 → 清洗碎片。

    返回 SplitResult（含切片列表 + 模式元信息）。
    """
    cleaned = _clean_lines(text)
    if not cleaned.strip():
        return SplitResult([], "empty", 0, 0)

    # 尝试条文切割
    articles = _split_by_article(cleaned)
    if articles is not None:
        # 条文模式：超长条文再做二级切割
        final: list[str] = []
        for art in articles:
            if len(art) <= _MAX_CHUNK_CHARS:
                final.append(art)
            else:
                final.extend(_split_paragraph(art))
        # 过滤碎片
        final = [c for c in final if len(c) >= _MIN_CHUNK_CHARS]
        return SplitResult(final, "article", len(articles), 0)

    # 降级到通用段落切割
    chunks = _split_paragraph(cleaned)
    # 过滤碎片
    chunks = [c for c in chunks if len(c) >= _MIN_CHUNK_CHARS]
    return SplitResult(chunks, "paragraph", 0, len(chunks))


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


def _dedup_chunks(chunks: list[dict], db: Session) -> tuple[list[dict], int]:
    """去重：剔除库中已存在的（同 source + 同 content）切片，及本批次内部重复。

    返回 (去重后待入库切片, 被跳过的重复数)。
    """
    if not chunks:
        return [], 0
    # 查库中已有 (source, content) 组合。按本批涉及的 source 收窄查询范围。
    sources = {c["source"] for c in chunks}
    existing = db.query(KnowledgeChunk.source, KnowledgeChunk.content).filter(
        KnowledgeChunk.source.in_(sources)
    ).all()
    seen: set[str] = {_chunk_key(s, c) for s, c in existing}

    kept: list[dict] = []
    skipped = 0
    for c in chunks:
        key = _chunk_key(c["source"], c["content"])
        if key in seen:
            skipped += 1
            continue
        seen.add(key)  # 同时拦截本批次内部重复
        kept.append(c)
    return kept, skipped


def _chunk_key(source: str, content: str) -> str:
    """切片唯一键：source + content 的 MD5，用于去重。"""
    return hashlib.md5(f"{source}\x00{content}".encode("utf-8")).hexdigest()


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
    split = _smart_split(payload.content)
    if not split.chunks:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "内容为空，无可导入切片")

    chunks = [{"category": payload.category, "source": payload.source, "content": p} for p in split.chunks]
    kept, skipped = _dedup_chunks(chunks, db)
    count = _do_index(kept, db) if kept else 0

    audit_log.record(
        db, user_id=user.id, action="import_knowledge", target=payload.category,
        detail=f"mode={split.mode} chunks={count} skipped={skipped}",
    )
    return {
        "category": payload.category,
        "source": payload.source,
        "imported_chunks": count,
        "skipped_duplicates": skipped,
        "split_mode": split.mode,
        "article_count": split.article_count,
    }


@router.post("/import-file")
async def import_knowledge_file(
    file: UploadFile = File(...),
    category: str = Form("law"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("legal", "admin")),
) -> dict:
    """上传文件批量导入知识库。支持 .txt / .docx / .pdf。

    智能切片：法规文本按「第X条」条文边界切割（保留单条完整语义），
    非法规文本降级为段落切割（每片 ≤500字）；两种模式均清洗页码/碎片行。
    入库前按 source + content 去重，同一文件重复导入不产生重复切片。
    """
    content = await _extract_file_text(file)
    split = _smart_split(content)
    if not split.chunks:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "文件内容为空或无法提取文本")

    source = file.filename or "未命名文件"
    chunks = [{"category": category, "source": source, "content": p} for p in split.chunks]
    kept, skipped = _dedup_chunks(chunks, db)
    count = _do_index(kept, db) if kept else 0

    audit_log.record(
        db, user_id=user.id,
        action="import_knowledge_file",
        target=source,
        detail=f"category={category} mode={split.mode} chunks={count} skipped={skipped}",
    )
    return {
        "source": source,
        "category": category,
        "imported_chunks": count,
        "skipped_duplicates": skipped,
        "split_mode": split.mode,
        "article_count": split.article_count,
    }


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
