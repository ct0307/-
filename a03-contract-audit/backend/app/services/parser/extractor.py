"""合同解析：PDF/Word → 纯文本 + 结构化要素。

文本抽取为真实实现（pdfplumber / python-docx / pypdf）。
要素抽取用正则做启发式抽取，覆盖常见字段；复杂条款后续交给 LLM 抽取增强。
扫描件 PDF 无文本层时抽取结果为空，后续接 OCR（风险点已记录）。
"""
import re

from app.core.logging import get_logger

log = get_logger("parser")


def extract_text(file_path: str) -> str:
    """按扩展名抽取合同纯文本。"""
    lower = file_path.lower()
    if lower.endswith(".pdf"):
        return _extract_pdf(file_path)
    if lower.endswith(".docx"):
        return _extract_docx(file_path)
    if lower.endswith(".txt"):
        with open(file_path, encoding="utf-8", errors="ignore") as f:
            return f.read()
    raise ValueError(f"不支持的文件类型: {file_path}")


def _extract_pdf(file_path: str) -> str:
    import pdfplumber

    parts: list[str] = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    text = "\n".join(parts).strip()
    if not text:
        log.warning("parser.pdf_empty", file=file_path, hint="可能是扫描件，需 OCR")
    return text


def _extract_docx(file_path: str) -> str:
    from docx import Document

    doc = Document(file_path)
    return "\n".join(p.text for p in doc.paragraphs).strip()


# 关键要素抽取规则：字段名 → 正则（取第一个捕获组）
_ELEMENT_PATTERNS: dict[str, str] = {
    "party_a": r"甲\s*方[：:]\s*([^\n，,；;]{2,50})",
    "party_b": r"乙\s*方[：:]\s*([^\n，,；;]{2,50})",
    "amount": r"(?:合同(?:金额|总价|总额)|价款|总金额)[^\d]{0,10}([￥¥]?\s?[\d,]+(?:\.\d+)?\s*(?:元|万元|人民币)?)",
    "sign_date": r"(?:签订|签署)(?:日期|时间|于)?[：:]?\s*(\d{4}\s*[-/年]\s*\d{1,2}\s*[-/月]\s*\d{1,2})",
    "duration": r"(?:合同期限|履约期限|有效期)[：:]?\s*([^\n，,；;。]{2,40})",
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
    log.info("parser.elements", extracted={k: v for k, v in elements.items() if v})
    return elements
