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

log = get_logger("parser")


@dataclass(frozen=True)
class DocumentParseResult:
    text: str
    source: Literal["native", "ocr", "mixed"]
    ocr_confidence: float | None = None
    requires_review: bool = False
    review_reason: str | None = None


@dataclass(frozen=True)
class _PDFTextCandidate:
    text: str
    page_texts: tuple[str, ...]


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
        return DocumentParseResult(_extract_docx_bytes(data), "native")
    if lower.endswith(".txt"):
        return DocumentParseResult(data.decode("utf-8", errors="ignore"), "native")
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
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                parts.append(page.extract_text() or "")
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
                return DocumentParseResult(alternate.text, "native")
        parts = [_normalize_compatibility_radicals(part) for part in parts]
        text = "\n".join(parts).strip()

    # 第二步：乱码检测 → PyMuPDF 降级
    if _is_garbled(text) and not radical_path_handled:
        log.info("parser.pdf_garbled", hint="检测到字体编码异常，切换 PyMuPDF 重新提取")
        text = _extract_pdf_pymupdf(data)
        if text and not _is_garbled(text):
            return DocumentParseResult(text, "native")
        parts = []

    if text and not empty_pages:
        return DocumentParseResult(text, "native")

    if not text:
        pymupdf_text = _extract_pdf_pymupdf(data)
        if pymupdf_text and not _is_garbled(pymupdf_text):
            return DocumentParseResult(pymupdf_text, "native")
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
    return DocumentParseResult(
        text=merged_text,
        source=source,
        ocr_confidence=result.mean_confidence,
        requires_review=result.requires_review,
        review_reason=review_reason,
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


def _extract_docx_bytes(data: bytes) -> str:
    """提取 docx 文本：段落 + 表格内容均读取。

    纯段落抽取会漏掉表格（基金合同/采购合同大量内容在表格中），
    必须遍历 doc.tables 补全，否则合同主体内容丢失。
    """
    from docx import Document

    doc = Document(io.BytesIO(data))
    parts: list[str] = []

    # 1. 段落文本
    for p in doc.paragraphs:
        if p.text.strip():
            parts.append(p.text)

    # 2. 表格文本（行列拼接，单元格间用空格分隔，行间用换行）
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append("  ".join(cells))

    return "\n".join(parts).strip()



# 关键要素抽取规则：字段名 → 正则（取第一个捕获组）
_ELEMENT_PATTERNS: dict[str, str] = {
    "party_a": r"甲\s*方[：:]\s*([^\n，,；;]{2,50})",
    "party_b": r"乙\s*方[：:]\s*([^\n，,；;]{2,50})",
    "amount": r"(?:合同(?:金额|总价|总额)|价款|总金额)[^\d]{0,10}([￥¥]?\s?[\d,]+(?:\.\d+)?\s*(?:元|万元|人民币)?)",
    "sign_date": r"(?:签订|签署)(?:日期|时间|于)?[：:]?\s*(\d{4}\s*[-/年]\s*\d{1,2}\s*[-/月]\s*\d{1,2})",
    "duration": r"(?:合同期限|履约期限|有效期)[：:]?\s*([^\n，,；;。]{2,40})",
    # 合同标的：覆盖"本合同标的为/乙方向甲方提供/第X条 合同标的"等主流写法
    "subject": r"(?:本合同标的为?|合同标的[：:]|乙方(?:向甲方)?(?:提供|承建|承租|销售|采购))[：:\s]*([^\n。]{8,80})",
    # 收付款节点：提取付款条款段落文本（最多8行），不强行结构化
    "payment_terms": r"(?:付款(?:方式|条款|计划|安排)|收付款)[^\n]*\n((?:[^\n]+\n?){1,8})",
}


def extract_elements(text: str) -> dict:
    """从合同文本抽取关键要素，返回结构化字段。

    每个字段返回抽取到的字符串，未命中则为 None，便于审查器判断"要素缺失"风险。
    """
    elements: dict[str, str | None] = {}
    for field, pattern in _ELEMENT_PATTERNS.items():
        m = re.search(pattern, text)
        elements[field] = m.group(1).strip() if m else None

    # 附带一些供审查器使用的信号
    elements["text_length"] = len(text)  # type: ignore[assignment]
    elements["has_breach_clause"] = bool(re.search(r"违约(?:责任|金|条款)", text))  # type: ignore[assignment]
    elements["has_dispute_clause"] = bool(re.search(r"争议(?:解决|处理)|仲裁|诉讼", text))  # type: ignore[assignment]
    fields = [field for field in _ELEMENT_PATTERNS if elements[field] is not None]
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
