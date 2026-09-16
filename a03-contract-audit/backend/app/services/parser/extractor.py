"""合同解析：PDF/Word → 纯文本 + 结构化要素。

文本抽取策略（PDF）：
  1. pdfplumber 优先（速度快，适合标准文本层 PDF）
  2. 乱码检测：CJK 字符占比 < 10% 且文本不为空 → 判定为字体编码问题
  3. PyMuPDF 降级（fitz）：对自定义字体无 ToUnicode 映射的 PDF 有更好兜底
  4. 仍为空/乱码 → 扫描件，需 OCR（路线图 P2，当前记 warning）

加密存储支持：启用 FILE_ENCRYPT_KEY 后，extract_text 自动解密再解析，调用方无感知。
"""
import io
import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from app.core.logging import get_logger
from app.core.config import settings
from app.services.parser.ocr import OCRResult, ocr_pdf_bytes
from app.services.parser.text_decoder import decode_text_bytes

log = get_logger("parser")


@dataclass(frozen=True)
class SourceAnchor:
    page_number: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    paragraph_index: int | None = None
    table_index: int | None = None
    row_index: int | None = None
    char_start: int | None = None
    char_end: int | None = None


@dataclass(frozen=True)
class DocumentBlock:
    block_id: str
    block_type: Literal["paragraph", "table_row", "page_text"]
    text: str
    anchor: SourceAnchor
    cells: tuple[str, ...] = ()
    style: str = ""
    confidence: float | None = None
    parse_source: Literal["native", "ocr"] = "native"


@dataclass(frozen=True)
class DocumentParseResult:
    text: str
    source: Literal["native", "ocr", "mixed"]
    ocr_confidence: float | None = None
    requires_review: bool = False
    review_reason: str | None = None
    blocks: tuple[DocumentBlock, ...] = ()


@dataclass(frozen=True)
class _PDFTextCandidate:
    text: str
    page_texts: tuple[str, ...]


@dataclass(frozen=True)
class _DocxImageMetrics:
    image_count: int
    meaningful_image_count: int


def _read_decrypted(file_path: str) -> bytes:
    """读取文件内容并按需解密。密钥未设置则返回原始字节（明文模式，向后兼容）。"""
    with open(file_path, "rb") as f:
        raw = f.read()
    from app.core.crypto import decrypt_bytes
    return decrypt_bytes(raw)


def extract_document(file_path: str) -> DocumentParseResult:
    """按扩展名抽取合同文本及解析质量。"""
    data = _read_decrypted(file_path)
    lower = file_path.lower()
    if lower.endswith(".pdf"):
        return _extract_pdf_result(data)
    if lower.endswith(".docx"):
        return _extract_docx_result(data)
    if lower.endswith(".txt"):
        return DocumentParseResult(decode_text_bytes(data).text, "native")
    raise ValueError(f"不支持的文件类型: {file_path}")


def extract_text(file_path: str) -> str:
    """按扩展名抽取合同纯文本。自动处理加密/明文两种存储模式。"""
    return extract_document(file_path).text


def _is_garbled(text: str) -> bool:
    """检测文本是否乱码：CJK 字符占比低于 10% 且文本非空视为字体编码异常。"""
    if not text or len(text) < 20:
        return False  # 空文本交给 empty 逻辑处理，不走此判断
    cjk = sum(1 for c in text if '一' <= c <= '鿿')
    return cjk / len(text) < 0.10


def _compatibility_radical_count(text: str) -> int:
    """统计 CJK 部首与康熙部首，不包含表意文字描述符。"""
    return sum(1 for char in text if "\u2e80" <= char <= "\u2fdf")


def _non_whitespace_length(text: str) -> int:
    return sum(1 for char in text if not char.isspace())


def _has_suspicious_radicals(text: str) -> bool:
    """仅在兼容部首数量或占比达到阈值时触发候选回退。"""
    count = _compatibility_radical_count(text)
    non_whitespace = _non_whitespace_length(text)
    return count >= 3 or bool(non_whitespace and count / non_whitespace >= 0.01)


def _readable_cjk_ratio(text: str) -> float:
    non_whitespace = _non_whitespace_length(text)
    if not non_whitespace:
        return 0.0
    cjk_count = sum(
        1
        for char in text
        if "\u3400" <= char <= "\u4dbf"
        or "\u4e00" <= char <= "\u9fff"
        or "\uf900" <= char <= "\ufaff"
    )
    return cjk_count / non_whitespace


def _prefer_pymupdf_text(primary: str, alternate: str) -> bool:
    """判断 PyMuPDF 候选是否在不丢失内容的前提下改善文本质量。"""
    primary_length = _non_whitespace_length(primary)
    alternate_length = _non_whitespace_length(alternate)
    if (
        not alternate_length
        or alternate_length < primary_length * 0.70
        or _has_suspicious_radicals(alternate)
    ):
        return False
    return (
        _compatibility_radical_count(alternate) < _compatibility_radical_count(primary)
        and _readable_cjk_ratio(alternate) >= _readable_cjk_ratio(primary)
    )


def _normalize_compatibility_radicals(text: str) -> str:
    """仅规范化异常兼容部首，保留其他字符和版面标记。"""
    return "".join(
        unicodedata.normalize("NFKC", char)
        if "\u2e80" <= char <= "\u2fdf"
        else char
        for char in text
    )


def _candidate_preserves_nonempty_pages(
    primary_pages: list[str],
    alternate: _PDFTextCandidate,
) -> bool:
    if len(alternate.page_texts) != len(primary_pages):
        return False
    return all(
        not primary.strip()
        or _non_whitespace_length(candidate) >= _non_whitespace_length(primary) * 0.70
        for primary, candidate in zip(primary_pages, alternate.page_texts)
    )


def _extract_pdf_result(data: bytes) -> DocumentParseResult:
    """PDF 文本提取：pdfplumber 优先，乱码时降级到 PyMuPDF。"""
    import pdfplumber

    # 第一步：pdfplumber
    parts: list[str] = []
    native_blocks: list[DocumentBlock] = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                page_text = page.extract_text() or ""
                parts.append(page_text)
                native_blocks.extend(
                    _extract_native_pdf_page_blocks(page, page_number, page_text)
                )
    except Exception as e:
        log.warning("parser.pdfplumber_error", error=str(e))
    text = "\n".join(parts).strip()
    empty_pages = tuple(index for index, part in enumerate(parts) if not part.strip())
    radical_path_handled = False

    # pdfplumber 可能把中文映射为 CJK/Kangxi 部首。此时仅在 PyMuPDF
    # 给出完整且质量更高的候选时替换，否则保留原文并局部规范化。
    if text and _has_suspicious_radicals(text):
        radical_path_handled = True
        if not empty_pages:
            expected_pages = len(parts) or None
            alternate = _extract_pdf_pymupdf_candidate(data, expected_pages=expected_pages)
            if (
                _candidate_preserves_nonempty_pages(parts, alternate)
                and _prefer_pymupdf_text(text, alternate.text)
            ):
                return DocumentParseResult(
                    alternate.text,
                    "native",
                    blocks=_page_text_blocks(alternate.page_texts),
                )
        parts = [_normalize_compatibility_radicals(part) for part in parts]
        native_blocks = [
            DocumentBlock(
                block_id=block.block_id,
                block_type=block.block_type,
                text=_normalize_compatibility_radicals(block.text),
                anchor=block.anchor,
                cells=block.cells,
                style=block.style,
                confidence=block.confidence,
                parse_source=block.parse_source,
            )
            for block in native_blocks
        ]
        text = "\n".join(parts).strip()

    # 第二步：乱码检测 → PyMuPDF 降级
    if _is_garbled(text) and not radical_path_handled:
        log.info("parser.pdf_garbled", hint="检测到字体编码异常，切换 PyMuPDF 重新提取")
        text = _extract_pdf_pymupdf(data)
        if text and not _is_garbled(text):
            return DocumentParseResult(text, "native", blocks=tuple(native_blocks))
        parts = []

    if text and not empty_pages:
        return DocumentParseResult(text, "native", blocks=tuple(native_blocks))

    if not text:
        pymupdf_text = _extract_pdf_pymupdf(data)
        if pymupdf_text and not _is_garbled(pymupdf_text):
            return DocumentParseResult(
                pymupdf_text,
                "native",
                blocks=(
                    DocumentBlock(
                        block_id="pdf-page-1",
                        block_type="page_text",
                        text=pymupdf_text,
                        anchor=SourceAnchor(page_number=1),
                    ),
                ),
            )
        log.warning("parser.pdf_empty", hint="文本层为空，进入离线 OCR")

    page_indices = empty_pages or None
    result = ocr_pdf_bytes(
        data,
        page_indices=page_indices,
        max_pages=settings.OCR_MAX_PAGES,
        max_page_pixels=settings.OCR_MAX_PAGE_PIXELS,
        dpi=settings.OCR_DPI,
        timeout_seconds=settings.OCR_TIMEOUT_SECONDS,
        min_confidence=settings.OCR_MIN_CONFIDENCE,
    )
    if isinstance(result, str):
        merged_text = "\n".join(part for part in (text, result.strip()) if part).strip()
        source = "mixed" if text or any(part.strip() for part in parts) else "ocr"
        return DocumentParseResult(merged_text, source)

    if result.requires_review:
        log.warning(
            "parser.ocr_review_required",
            confidence=result.mean_confidence,
            pages=result.page_count,
        )
    if parts and empty_pages and len(result.page_texts) == len(empty_pages):
        merged = list(parts)
        for index, page_text in zip(empty_pages, result.page_texts):
            merged[index] = page_text
        merged_text = "\n".join(part for part in merged if part).strip()
    else:
        merged_text = "\n".join(part for part in (text, result.text) if part).strip()

    source = "mixed" if text or any(part.strip() for part in parts) else "ocr"
    review_reason = None
    if result.requires_review:
        threshold = int(settings.OCR_MIN_CONFIDENCE * 100)
        review_reason = (
            f"OCR 平均置信度低于 {threshold}%"
            if result.text
            else "OCR 未识别出有效文本"
        )
    if parts and empty_pages and len(result.page_texts) == len(empty_pages):
        ocr_page_set = set(empty_pages)
        blocks_list: list[DocumentBlock] = []
        for index, page_text in enumerate(merged):
            page_number = index + 1
            if index in ocr_page_set:
                if page_text.strip():
                    blocks_list.append(DocumentBlock(
                        block_id=f"pdf-page-{page_number}",
                        block_type="page_text",
                        text=page_text,
                        anchor=SourceAnchor(page_number=page_number),
                        confidence=result.mean_confidence,
                        parse_source="ocr",
                    ))
            else:
                blocks_list.extend(
                    block for block in native_blocks
                    if block.anchor.page_number == page_number
                )
        blocks = tuple(blocks_list)
    else:
        blocks = _page_text_blocks(
            result.page_texts or ((result.text,) if result.text else ()),
            parse_source="ocr",
            confidence=result.mean_confidence,
        )
    return DocumentParseResult(
        text=merged_text,
        source=source,
        ocr_confidence=result.mean_confidence,
        requires_review=result.requires_review,
        review_reason=review_reason,
        blocks=blocks,
    )


def _extract_pdf_bytes(data: bytes) -> str:
    """兼容旧调用方，仅返回 PDF 文本。"""
    return _extract_pdf_result(data).text


def _extract_pdf_pymupdf_candidate(
    data: bytes,
    expected_pages: int | None = None,
) -> _PDFTextCandidate:
    """提取 PyMuPDF 文本，并保留页级结果供完整性校验。"""
    doc = None
    try:
        import fitz  # pymupdf

        doc = fitz.open(stream=data, filetype="pdf")
        if expected_pages is not None and len(doc) != expected_pages:
            log.warning(
                "parser.pymupdf_page_count_mismatch",
                expected_pages=expected_pages,
            )
            return _PDFTextCandidate("", ())
        parts: list[str] = []
        for page in doc:
            parts.append(page.get_text("text") or "")
        text = "\n".join(parts).strip()
        if text:
            log.info("parser.pymupdf_ok", chars=len(text))
        return _PDFTextCandidate(text, tuple(parts))
    except Exception as e:
        log.warning("parser.pymupdf_error", error=str(e))
        return _PDFTextCandidate("", ())
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                log.warning("parser.pymupdf_close_error")


def _extract_pdf_pymupdf(data: bytes, expected_pages: int | None = None) -> str:
    """兼容旧调用方，仅返回 PyMuPDF 提取的整体文本。"""
    return _extract_pdf_pymupdf_candidate(data, expected_pages=expected_pages).text


def _page_text_blocks(
    page_texts: tuple[str, ...],
    *,
    parse_source: Literal["native", "ocr"] = "native",
    confidence: float | None = None,
) -> tuple[DocumentBlock, ...]:
    return tuple(
        DocumentBlock(
            block_id=f"pdf-page-{page_number}",
            block_type="page_text",
            text=text,
            anchor=SourceAnchor(page_number=page_number),
            confidence=confidence,
            parse_source=parse_source,
        )
        for page_number, text in enumerate(page_texts, start=1)
        if text.strip()
    )


def _extract_native_pdf_page_blocks(
    page: object,
    page_number: int,
    fallback_text: str,
) -> tuple[DocumentBlock, ...]:
    """优先把带坐标的 PDF 词聚合为行块；无坐标接口时降级为页块。"""
    extract_words = getattr(page, "extract_words", None)
    words: list[dict] = []
    if callable(extract_words):
        try:
            words = list(extract_words(keep_blank_chars=False, use_text_flow=True) or ())
        except Exception as exc:
            log.warning(
                "parser.pdf_word_positions_unavailable",
                page_number=page_number,
                exception_type=type(exc).__name__,
            )
    positioned = [
        word for word in words
        if str(word.get("text", "")).strip()
        and all(key in word for key in ("x0", "top", "x1", "bottom"))
    ]
    if positioned:
        lines: list[list[dict]] = []
        for word in sorted(positioned, key=lambda item: (float(item["top"]), float(item["x0"]))):
            if not lines or abs(float(word["top"]) - float(lines[-1][0]["top"])) > 3.0:
                lines.append([word])
            else:
                lines[-1].append(word)
        return tuple(
            DocumentBlock(
                block_id=f"pdf-page-{page_number}-line-{line_index}",
                block_type="page_text",
                text=" ".join(str(word["text"]).strip() for word in line),
                anchor=SourceAnchor(
                    page_number=page_number,
                    bbox=(
                        min(float(word["x0"]) for word in line),
                        min(float(word["top"]) for word in line),
                        max(float(word["x1"]) for word in line),
                        max(float(word["bottom"]) for word in line),
                    ),
                ),
            )
            for line_index, line in enumerate(lines, start=1)
        )
    if not fallback_text.strip():
        return ()
    width = getattr(page, "width", None)
    height = getattr(page, "height", None)
    bbox = (
        (0.0, 0.0, float(width), float(height))
        if width is not None and height is not None
        else None
    )
    return (
        DocumentBlock(
            block_id=f"pdf-page-{page_number}",
            block_type="page_text",
            text=fallback_text,
            anchor=SourceAnchor(page_number=page_number, bbox=bbox),
        ),
    )


def _extract_docx_result(data: bytes) -> DocumentParseResult:
    """提取 docx 文本：段落 + 表格内容均读取。

    按正文 XML 顺序遍历段落和表格，保留可回溯的段落/表格行锚点。
    """
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(io.BytesIO(data))
    parts: list[str] = []
    blocks: list[DocumentBlock] = []
    paragraph_index = 0
    table_index = 0
    for item in doc.iter_inner_content():
        if isinstance(item, Paragraph):
            text = item.text.strip()
            current_index = paragraph_index
            paragraph_index += 1
            if not text:
                continue
            parts.append(text)
            blocks.append(DocumentBlock(
                block_id=f"docx-paragraph-{current_index}",
                block_type="paragraph",
                text=text,
                anchor=SourceAnchor(paragraph_index=current_index),
                style=str(item.style.name or "") if item.style else "",
            ))
            continue
        if isinstance(item, Table):
            current_table = table_index
            table_index += 1
            for row_index, row in enumerate(item.rows):
                cells = tuple(cell.text.strip() for cell in row.cells if cell.text.strip())
                if not cells:
                    continue
                text = "  ".join(cells)
                parts.append(text)
                blocks.append(DocumentBlock(
                    block_id=f"docx-table-{current_table}-row-{row_index}",
                    block_type="table_row",
                    text=text,
                    anchor=SourceAnchor(table_index=current_table, row_index=row_index),
                    cells=cells,
                ))
    text = "\n".join(parts).strip()
    image_metrics = _docx_image_metrics(doc)
    text_length = _non_whitespace_length(text)
    requires_review = False
    review_reason = None
    if text_length < 200 and image_metrics.meaningful_image_count > 0:
        requires_review = True
        review_reason = "DOCX 疑似图片型文档，未提取到足够正文"
    elif text_length == 0:
        requires_review = True
        review_reason = "DOCX 正文为空"

    return DocumentParseResult(
        text,
        "native",
        requires_review=requires_review,
        review_reason=review_reason,
        blocks=tuple(blocks),
    )


def _docx_image_metrics(document) -> _DocxImageMetrics:
    from docx.image.image import Image

    image_parts = tuple(document.part.package.image_parts)
    meaningful_image_count = 0
    for part in image_parts:
        image = Image.from_blob(part.blob)
        width = int(image.px_width or 0)
        height = int(image.px_height or 0)
        if width * height >= 1_500_000 and min(width, height) >= 900:
            meaningful_image_count += 1
    return _DocxImageMetrics(
        image_count=len(image_parts),
        meaningful_image_count=meaningful_image_count,
    )


def _extract_docx_bytes(data: bytes) -> str:
    """兼容旧调用方，仅返回 DOCX 纯文本。"""
    return _extract_docx_result(data).text



_SIGN_DATE_PATTERN = (
    r"(?:签订|签署)(?:日期|时间|于)?[：:]?\s*"
    r"(\d{4}\s*[-/年]\s*\d{1,2}\s*[-/月]\s*\d{1,2})"
)


def extract_elements(text: str) -> dict:
    """兼容旧调用方的扁平结果；新解析链路使用 ``extract_element_result``。"""
    from app.services.parser.elements import extract_element_result, legacy_element_values

    result = extract_element_result(DocumentParseResult(text=text, source="native"))
    elements = legacy_element_values(result.values, text=text)
    fields = [
        field for field in (*result.values, "sign_date")
        if elements[field] not in (None, [])
    ]
    log.info(
        "parser.elements",
        fields=fields,
        field_count=len(fields),
        text_length=len(text),
        has_breach_clause=elements["has_breach_clause"],
        has_dispute_clause=elements["has_dispute_clause"],
    )
    return elements


# ---------------------------------------------------------------------------
# LLM 要素抽取（方案 A）：正则兜底 + LLM 补语义字段
# ---------------------------------------------------------------------------

def _parse_json_obj(text: str) -> dict:
    """从 LLM 输出中提取 JSON 对象，容错代码块围栏与前后噪声。"""
    cleaned = re.sub(r"```(?:json)?|```", "", text).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("LLM 输出未找到 JSON 对象")
    import json as _json
    return _json.loads(cleaned[start:end + 1])


def _build_extract_excerpt(text: str, max_chars: int = 5000) -> str:
    """智能截取合同文本：前 3500 字覆盖甲乙方/标的，尾部附付款段落（最多 1500 字）。

    付款条款常位于合同中后部，纯截前段会遗漏，故单独定位追加。
    """
    head = text[:3500]
    pay_m = re.search(r"(?:付款|收款|付款方式|结算方式|收付款)[^\n]{0,30}", text)
    tail = ""
    if pay_m:
        s = max(0, pay_m.start() - 100)
        segment = text[s: s + 1500]
        if segment not in head:  # 避免重复
            tail = "\n……\n" + segment
    return (head + tail)[:max_chars]


def llm_extract_elements(text: str) -> dict | None:
    """用 LLM 从合同文本中抽取六个核心要素，返回 dict；调用失败返回 None。

    字段：party_a / party_b / subject / payment_terms / amount / duration。
    失败时返回 None，调用方用正则结果兜底，链路不因 LLM 不可用而中断。
    """
    from app.llm.factory import get_llm_adapter
    from app.llm.base import LLMError
    import json as _json

    excerpt = _build_extract_excerpt(text)
    system = (
        "你是合同要素提取助手。从给定的合同文本中准确提取关键要素，"
        "只返回 JSON 对象，不要任何解释或代码块。"
        "字段说明：party_a（甲方全称）、party_b（乙方全称）、"
        "subject（合同标的，简洁描述，不超过60字）、"
        "payment_terms（收付款安排，保留关键节点和金额比例，不超过150字）、"
        "amount（合同总金额，含单位）、duration（合同期限）。"
        "找不到的字段填 null。"
        "示例格式：{\"party_a\":\"XX有限公司\",\"party_b\":\"YY公司\","
        "\"subject\":\"软件定制开发\",\"payment_terms\":\"签订后30天付30%……\","
        "\"amount\":\"100万元\",\"duration\":\"12个月\"}"
    )
    user = f"请提取以下合同的要素：\n\n{excerpt}"
    try:
        adapter = get_llm_adapter()
        resp = adapter.chat(system, user, temperature=0.1)
        result = _parse_json_obj(resp.text)
        # 只保留预期字段，防止 LLM 输出意外字段
        allowed = {"party_a", "party_b", "subject", "payment_terms", "amount", "duration"}
        cleaned = {k: v for k, v in result.items() if k in allowed and v}
        log.info("parser.llm_extract_ok", fields=list(cleaned.keys()))
        return cleaned
    except (LLMError, ValueError, Exception) as exc:
        log.warning("parser.llm_extract_failed", error=str(exc))
        return None


def extract_elements_with_llm(text: str) -> dict:
    """要素抽取升级版：正则先跑保留审查信号，LLM 补/覆盖六个语义要素。

    供 parse 端点调用（精解析场景）；批量上传和审查器继续用 extract_elements（纯正则，速度优先）。
    LLM 失败时静默降级为纯正则结果，链路不中断。
    """
    # Step 1：正则抽取（保留 text_length / has_* 审查信号，这些字段不走 LLM）
    base = extract_elements(text)

    # Step 2：LLM 补/覆盖六要素（只覆盖有值的字段，不用 null 覆盖正则的正确结果）
    llm_result = llm_extract_elements(text)
    if llm_result:
        for key in ("party_a", "party_b", "subject", "payment_terms", "amount", "duration"):
            if llm_result.get(key):
                base[key] = llm_result[key]
    else:
        log.info("parser.llm_fallback", hint="LLM 提取失败，使用纯正则结果")

    return base
