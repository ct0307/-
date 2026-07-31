"""知识库端点：导入法规/行业规则/合同模板，切片向量化供 RAG 检索；查询卡片/统计。"""
import hashlib
import io
import json
import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.config import settings
from app.db.session import get_db
from app.llm.base import LLMError
from app.models.models import KnowledgeChunk, User
from app.schemas.contract import KnowledgeImport
from app.services import audit_log
from app.services.rag.retriever import (
    build_documents_without_embeddings,
    normalize_scope_metadata,
    prepare_documents,
)

router = APIRouter()

# 切片长度上限（字符）：bge-small-zh 有效窗口约 400 中文字符，留 20 字余量。
_MAX_CHUNK_CHARS = 380
# 切片长度下限（字符）：短于此的碎片视为噪音丢弃。
_MIN_CHUNK_CHARS = 20

# 法条条文起始标记：「第X条」，行首锚定防交叉引用误判。
_ARTICLE_RE = re.compile(r"^[\t 　]*第[一二三四五六七八九十百千零两\d]{1,7}条", re.MULTILINE)

# 章节标题标记：「第X章/编/节 标题」，用于为法条切片附加章节上下文。
_CHAPTER_RE = re.compile(
    r"^[\t 　]*第[一二三四五六七八九十百千零两\d]{1,5}[章编节篇][^\n]{0,30}$",
    re.MULTILINE,
)

# 款项编号标记：合同模板常见的多级编号格式。
# 匹配：1.1 / 1.1.1 / 一、 / （一） / (1) / 1、
# ≥3 命中才认定为款项模式，避免把普通段落里偶发数字误触发。
_CLAUSE_RE = re.compile(
    r"^[\t 　]*("
    r"\d+\.\d+(?:\.\d+)?[\s　]"    # 1.1  1.1.1
    r"|[一二三四五六七八九十]+[、]"  # 一、 二、
    r"|[（(][一二三四五六七八九十百\d]+[）)]"  # （一）(1)
    r"|\d+[、]"                     # 1、
    r")",
    re.MULTILINE,
)

# 纯噪音行判定：页码（- 3 -/第3页/共10页/3/25）、纯符号等。
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


def _chips_for(cat_label: str, source: str | None) -> list[str]:
    """根据分类和来源生成卡片标签列表。"""
    chips: list[str] = [cat_label]
    if source:
        # 去掉常见文件扩展名，截断过长来源名
        name = source.rsplit(".", 1)[0] if "." in source else source
        name = name[:20] + "…" if len(name) > 20 else name
        if name and name != cat_label:
            chips.append(name)
    return chips


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
    """按「第X条」边界切割，每条前缀最近章节标题以补充上下文。

    例：【第三章 违约责任】\n第五十八条 当事人可以…
    ≥2 条命中才启动，否则返回 None 降级。
    """
    article_matches = list(_ARTICLE_RE.finditer(text))
    if len(article_matches) < 2:
        return None

    # 章节标题位置表：(offset, 标题文本)
    chapters: list[tuple[int, str]] = [
        (m.start(), m.group(0).strip()) for m in _CHAPTER_RE.finditer(text)
    ]

    articles: list[str] = []
    for i, m in enumerate(article_matches):
        start = m.start()
        end = article_matches[i + 1].start() if i + 1 < len(article_matches) else len(text)
        chunk = text[start:end].strip()
        if not chunk:
            continue

        # 找最近的前置章节标题（倒序找第一个 offset < start 的）
        prefix = ""
        for ch_pos, ch_title in reversed(chapters):
            if ch_pos < start:
                prefix = f"【{ch_title}】\n"
                break

        articles.append(prefix + chunk)
    return articles


def _split_by_clause(text: str) -> list[str] | None:
    """按合同款项编号边界切割（1.1 / 一、 / （一） 等）。

    ≥3 命中才启动，避免普通段落偶发数字误触发。
    返回 None 则降级到段落切割。
    """
    matches = list(_CLAUSE_RE.finditer(text))
    if len(matches) < 3:
        return None

    clauses: list[str] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        if chunk:
            clauses.append(chunk)
    return clauses


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
            if len(sent) > _MAX_CHUNK_CHARS:
                if buf.strip():
                    chunks.append(buf.strip())
                    buf = ""
                chunks.extend(_hard_split(sent))
                continue
            if len(buf) + len(sent) > _MAX_CHUNK_CHARS and buf:
                chunks.append(buf)
                buf = ""
            buf += sent
        if buf.strip():
            chunks.append(buf.strip())
    return chunks


def _hard_split(text: str, limit: int = _MAX_CHUNK_CHARS) -> list[str]:
    """无句界长文本按字符硬切；法规续片重复条文前缀以保留定位。"""
    stripped = text.strip()
    if len(stripped) <= limit:
        return [stripped] if stripped else []
    prefix_match = re.match(
        r"^(?P<prefix>(?:【[^\n]{1,40}】\n)?第[一二三四五六七八九十百千零两\d]{1,7}条\s*)",
        stripped,
    )
    prefix = prefix_match.group("prefix") if prefix_match else ""
    chunks = [stripped[:limit]]
    remaining = stripped[limit:]
    continuation_limit = max(1, limit - len(prefix))
    while remaining:
        body = remaining[:continuation_limit]
        chunks.append(f"{prefix}{body}" if prefix else body)
        remaining = remaining[continuation_limit:]
    return [chunk.strip() for chunk in chunks if chunk.strip()]


class SplitResult:
    """智能切片结果，携带模式元信息供前端展示。"""
    __slots__ = ("chunks", "mode", "article_count", "paragraph_count", "filtered_placeholders")

    def __init__(self, chunks: list[str], mode: str, article_count: int, paragraph_count: int, filtered_placeholders: int = 0):
        self.chunks = chunks
        self.mode = mode
        self.article_count = article_count
        self.paragraph_count = paragraph_count
        self.filtered_placeholders = filtered_placeholders


# 占位符模式：「第X条 章节标题第X条内容」格式——自动生成的假条文，无实质法律内容。
# 匹配：「第96条 附则第96条内容」「第51条 特别规定第51条内容」等。
_PLACEHOLDER_RE = re.compile(
    r"^第[一二三四五六七八九十百千零两\d]{1,7}[条款项]\s+[^\n]{0,30}第[一二三四五六七八九十百千零两\d]{1,7}[条款项]内容\s*$"
)


def _is_placeholder(chunk: str) -> bool:
    """判断切片是否为占位文本（自动生成、无语义价值）。"""
    return bool(_PLACEHOLDER_RE.match(chunk.strip()))


def _smart_split(text: str) -> SplitResult:
    """智能切片三条路径：法条 → 款项 → 段落，逐级降级。

    最终过滤：长度 < _MIN_CHUNK_CHARS 的碎片 + 占位符条文。
    返回 SplitResult（含切片列表 + 模式元信息 + 过滤掉的占位符数）。
    """
    cleaned = _clean_lines(text)
    if not cleaned.strip():
        return SplitResult([], "empty", 0, 0)

    def _filter(chunks: list[str]) -> tuple[list[str], int]:
        """过滤碎片和占位符，返回 (保留列表, 被过滤占位符数)。"""
        kept, placeholder_count = [], 0
        for c in chunks:
            if len(c) < _MIN_CHUNK_CHARS:
                continue
            if _is_placeholder(c):
                placeholder_count += 1
                continue
            kept.append(c)
        return kept, placeholder_count

    # 路径 1：法规法条模式（第X条边界 + 章节前缀）
    articles = _split_by_article(cleaned)
    if articles is not None:
        final: list[str] = []
        for art in articles:
            if len(art) <= _MAX_CHUNK_CHARS:
                final.append(art)
            else:
                final.extend(_split_paragraph(art))
        final, ph = _filter(final)
        return SplitResult(final, "article", len(articles), 0, ph)

    # 路径 2：合同款项模式（1.1 / 一、 / （一）编号边界）
    clauses = _split_by_clause(cleaned)
    if clauses is not None:
        final = []
        for cl in clauses:
            if len(cl) <= _MAX_CHUNK_CHARS:
                final.append(cl)
            else:
                final.extend(_split_paragraph(cl))
        final, ph = _filter(final)
        return SplitResult(final, "clause", 0, len(final), ph)

    # 路径 3：通用段落切割
    chunks = _split_paragraph(cleaned)
    chunks, ph = _filter(chunks)
    return SplitResult(chunks, "paragraph", 0, len(chunks), ph)


async def _extract_file_text(file: UploadFile) -> str:
    """从上传文件提取纯文本。支持 txt / docx / pdf。

    docx：按文档顺序合并段落 + 表格（表格单元格用「|」分隔），避免表格条款丢失。
    pdf ：pdfplumber 文字提取；扫描件（extract_text 返回空）抛 400 明确提示。
    txt ：utf-8 / gbk / utf-8-sig 三编码兜底。
    """
    raw = await file.read()
    if len(raw) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"文件超过 {settings.MAX_UPLOAD_MB}MB 上限",
        )
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
            parts: list[str] = []
            # 1. 主体段落（按文档顺序）
            for p in doc.paragraphs:
                if p.text.strip():
                    parts.append(p.text.strip())
            # 2. 表格（每行单元格以「|」拼接，行间空行分隔）
            for tbl in doc.tables:
                for row in tbl.rows:
                    cells = [c.text.strip() for c in row.cells if c.text.strip()]
                    if cells:
                        parts.append(" | ".join(cells))
            return "\n\n".join(parts)
        except Exception as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"docx 解析失败：{exc}") from exc

    if fname.endswith(".pdf"):
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(raw)) as pdf:
                pages = [p.extract_text() or "" for p in pdf.pages]
            text = "\n\n".join(t for t in pages if t.strip())
            if not text.strip():
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "PDF 未能提取到文字（可能是扫描件/图像 PDF），请转换为文字版 PDF 或 .txt 后重新导入",
                )
            return text
        except HTTPException:
            raise
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


def _detect_category(text: str, split_mode: str) -> str:
    """基于文本内容和切片模式精确判断知识库分类。

    识别优先级：
    1. 法条切片模式（split_mode='article'）→ 法律法规，最可靠
    2. 裁判文书关键词 → 典型案例
    3. 合同双方结构 → 标准条款
    4. 审查规则关键词 → 风险规则
    5. 兜底 → 法律法规
    """
    # 最可靠判断：已检出「第X条」法条结构
    if split_mode == "article":
        return "law"

    # 取前 2000 字做关键词扫描（性能优先，开头通常最具代表性）
    sample = text[:2000]

    # 典型案例：案号格式「（2023）粤01民终XXX号」或裁判文书类型词
    if re.search(r"案\s*号|裁判文书|判\s*决\s*书|裁\s*定\s*书|（\d{4}）.{1,12}[号]", sample):
        return "case"

    # 标准条款/合同模板：双方角色 + 协议签署结构
    if re.search(
        r'甲\s*方.*?乙\s*方|签订本[合协]同|本[合协]议由|特此[协]议|双方协商一致|以下简称[「"]?[甲乙]方',
        sample,
    ):
        return "template"

    # 风险规则：审查规则、合规要求类措辞
    if re.search(
        r"风险点|审查要点|注意事项|合规要求|风控规则|应当.*?约定|不得.*?条款|必须.*?明确|建议.*?条款",
        sample,
    ):
        return "rule"

    # 兜底：法律法规（知识库法规占比最大，无特征时最保险）
    return "law"


def _do_index(chunks: list[dict], db: Session) -> int:
    """切片向量化入库，embedding 不可用时降级写空向量。"""
    try:
        rows = prepare_documents(chunks)
    except LLMError:
        rows = build_documents_without_embeddings(chunks)
    try:
        for row in rows:
            db.add(row)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return len(rows)


def _parse_scope_form(
    scope_mode: str,
    applicable_contract_types: str,
    applicable_dimensions: str,
) -> dict:
    try:
        contract_types = json.loads(applicable_contract_types or "[]")
        dimensions = json.loads(applicable_dimensions or "[]")
        if not isinstance(contract_types, list) or not isinstance(dimensions, list):
            raise ValueError("applicability fields must be JSON arrays")
        return normalize_scope_metadata(scope_mode, contract_types, dimensions)
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


def _replace_source_chunks(db: Session, source: str, chunks: list[dict]) -> tuple[int, int]:
    """先完整准备新行，再用单次事务替换来源；失败时旧知识可回滚。"""
    try:
        rows = prepare_documents(chunks)
    except LLMError:
        rows = build_documents_without_embeddings(chunks)
    try:
        deleted = db.query(KnowledgeChunk).filter(KnowledgeChunk.source == source).delete()
        for row in rows:
            db.add(row)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return deleted, len(rows)


@router.post("/import")
def import_knowledge(
    payload: KnowledgeImport,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("legal", "admin")),
) -> dict:
    split = _smart_split(payload.content)
    if not split.chunks:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "内容为空，无可导入切片")

    metadata = payload.model_dump(exclude={"category", "source", "content"})
    chunks = [
        {"category": payload.category, "source": payload.source, "content": p, **metadata}
        for p in split.chunks
    ]
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
    category: str = Form("auto"),
    overwrite: bool = Form(False),
    scope_mode: str = Form("unclassified"),
    applicable_contract_types: str = Form("[]"),
    applicable_dimensions: str = Form("[]"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("legal", "admin")),
) -> dict:
    """上传文件批量导入知识库。支持 .txt / .docx / .pdf。

    category 传 "auto"（默认）时自动识别分类：
    - 检出法条结构（第X条）→ 法律法规
    - 含裁判文书字样 → 典型案例
    - 含甲方乙方/签订结构 → 标准条款
    - 含风险点/审查要点 → 风险规则
    - 兜底 → 法律法规

    也可显式传 law / rule / template / case 强制指定分类。
    """
    content = await _extract_file_text(file)
    split = _smart_split(content)
    if not split.chunks:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "文件内容为空或无法提取文本")

    # 自动识别或使用指定分类
    auto_detect = category == "auto"
    final_category = _detect_category(content, split.mode) if auto_detect else category

    source = file.filename or "未命名文件"

    scope_metadata = _parse_scope_form(
        scope_mode, applicable_contract_types, applicable_dimensions
    )
    chunks = [
        {"category": final_category, "source": source, "content": p, **scope_metadata}
        for p in split.chunks
    ]
    if overwrite:
        kept, skipped = chunks, 0
        deleted, count = _replace_source_chunks(db, source, kept)
    else:
        deleted = 0
        kept, skipped = _dedup_chunks(chunks, db)
        count = _do_index(kept, db) if kept else 0

    # 重叠预警：通过条文编号对比（精确），兜底用同分类条数阈值
    overlap_warning = _check_article_overlap(split.chunks, final_category, source, db)
    if not overlap_warning:
        other_count = (
            db.query(func.count(KnowledgeChunk.id))
            .filter(KnowledgeChunk.category == final_category, KnowledgeChunk.source != source)
            .scalar() or 0
        )
        if count > 0 and other_count > 200:
            overlap_warning = (
                f"当前分类「{_CAT_LABEL.get(final_category, final_category)}」"
                f"库中已有来自其他来源的 {other_count} 条，请确认是否与本次导入存在语义重叠。"
            )

    # 过滤占位符数量
    filtered_placeholders = split.filtered_placeholders

    audit_log.record(
        db, user_id=user.id,
        action="import_knowledge_file",
        target=source,
        detail=(
            f"category={final_category} auto={auto_detect} overwrite={overwrite} "
            f"deleted={deleted} mode={split.mode} chunks={count} "
            f"skipped={skipped} placeholders_filtered={filtered_placeholders}"
        ),
    )
    return {
        "source": source,
        "category": final_category,
        "detected_category": final_category if auto_detect else None,
        "auto_detected": auto_detect,
        "overwrite": overwrite,
        "deleted_chunks": deleted,
        "imported_chunks": count,
        "skipped_duplicates": skipped,
        "filtered_placeholders": filtered_placeholders,
        "split_mode": split.mode,
        "article_count": split.article_count,
        "overlap_warning": overlap_warning,
    }


def _check_article_overlap(chunks: list[str], category: str, source: str, db: Session) -> str | None:
    """通过条文编号检测内容重叠：提取新切片的「第X条」编号集，与库中同分类条目对比。

    重叠率 > 50% → 同一法律已在库中，给出精确来源提示（精确到已有哪个文件）。
    比文件名关键词匹配更可靠：直接看内容结构，不依赖文件命名规范。
    """
    # 提取新切片的条文编号集
    _ART_NUM_RE = re.compile(r"第([一二三四五六七八九十百千零两\d]{1,7})条")
    new_articles: set[str] = set()
    for chunk in chunks:
        for m in _ART_NUM_RE.finditer(chunk):
            new_articles.add(m.group(1))

    if len(new_articles) < 5:  # 条文数太少（段落文本、规则等），不做条文级对比
        return None

    # 查库里同分类的条文编号分布（按source统计）
    existing = (
        db.query(KnowledgeChunk.source, KnowledgeChunk.content)
        .filter(KnowledgeChunk.category == category, KnowledgeChunk.source != source)
        .all()
    )

    # 统计每个source与新文件的条文编号重叠数
    source_overlap: dict[str, int] = {}
    for row_source, content in existing:
        for m in _ART_NUM_RE.finditer(content):
            art_num = m.group(1)
            if art_num in new_articles:
                source_overlap[row_source] = source_overlap.get(row_source, 0) + 1

    if not source_overlap:
        return None

    # 找重叠最多的来源，计算重叠率
    top_source = max(source_overlap, key=lambda k: source_overlap[k])
    overlap_count = source_overlap[top_source]
    overlap_ratio = overlap_count / len(new_articles)

    if overlap_ratio >= 0.5:
        return (
            f"检测到库中「{top_source}」与本文件有 {overlap_count} 个相同条文编号"
            f"（重叠率 {overlap_ratio:.0%}），可能是同一法律的不同版本。"
            f"建议先删除旧版本或开启「覆盖同名旧数据」。"
        )
    return None
    """卡片标签：分类中文 + 来源关键片段。"""
    chips = [cat_label]
    # 从来源名里取书名号内内容或末段作为第二个 chip
    m = re.search(r"《([^》]+)》", source)
    if m:
        chips.append(m.group(1))
    return chips[:3]


@router.get("/cards")
def knowledge_cards(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    size: int = Query(24, ge=1, le=100, description="每页条数"),
    q: str = Query("", description="关键词模糊搜索（source + content）"),
    category: str = Query("", description="按 category 英文键过滤，空字符串=全部"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """知识库卡片分页列表。支持关键词搜索与分类过滤。
    返回 {total, page, size, items}，items 形状对齐前端 KnowledgeCard。
    """
    query = db.query(KnowledgeChunk)
    if q:
        query = query.filter(
            KnowledgeChunk.source.contains(q) | KnowledgeChunk.content.contains(q)
        )
    if category:
        query = query.filter(KnowledgeChunk.category == category)

    total: int = query.with_entities(func.count(KnowledgeChunk.id)).scalar() or 0
    offset = (page - 1) * size
    rows = query.order_by(KnowledgeChunk.created_at.desc()).offset(offset).limit(size).all()

    items: list[dict] = []
    for c in rows:
        cat_label = _CAT_LABEL.get(c.category, "风险规则")
        desc = c.content if len(c.content) <= _DESC_MAX else c.content[:_DESC_MAX] + "…"
        items.append({
            "id": f"K{c.id:02d}",
            "title": c.source or c.content[:20],
            "cat": cat_label,
            "desc": desc,
            "chips": _chips_for(cat_label, c.source),
            "date": c.created_at.strftime("%Y-%m-%d") if c.created_at else "",
        })
    return {"total": total, "page": page, "size": size, "items": items}


@router.get("/stats")
def knowledge_stats(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """知识库分类统计，形状对齐前端 KNOWLEDGE_STATS（cat/count）。四类恒定展示。"""
    rows = dict(db.query(KnowledgeChunk.category, func.count(KnowledgeChunk.id)).group_by(KnowledgeChunk.category).all())
    order = ["law", "template", "rule", "case"]
    return [{"cat": _CAT_LABEL[k], "count": rows.get(k, 0)} for k in order]


@router.get("/{chunk_id}")
def get_knowledge_detail(
    chunk_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """单条知识库详情，返回完整 content（不截断）。"""
    chunk = db.query(KnowledgeChunk).filter(KnowledgeChunk.id == chunk_id).first()
    if not chunk:
        raise HTTPException(status_code=404, detail="知识条目不存在")
    cat_label = _CAT_LABEL.get(chunk.category, "风险规则")
    return {
        "id": chunk.id,
        "title": chunk.source or chunk.content[:20],
        "cat": cat_label,
        "content": chunk.content,
        "date": chunk.created_at.strftime("%Y-%m-%d") if chunk.created_at else "",
    }

@router.delete("/{chunk_id}")
def delete_knowledge(
    chunk_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(["admin"])),
) -> dict:
    """删除单条知识库条目（仅 admin）。"""
    chunk = db.query(KnowledgeChunk).filter(KnowledgeChunk.id == chunk_id).first()
    if not chunk:
        raise HTTPException(status_code=404, detail="知识条目不存在")
    db.delete(chunk)
    db.commit()
    return {"deleted": chunk_id}
