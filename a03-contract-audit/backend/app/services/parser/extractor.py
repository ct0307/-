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

from app.core.logging import get_logger

log = get_logger("parser")


def _read_decrypted(file_path: str) -> bytes:
    """读取文件内容并按需解密。密钥未设置则返回原始字节（明文模式，向后兼容）。"""
    with open(file_path, "rb") as f:
        raw = f.read()
    from app.core.crypto import decrypt_bytes
    return decrypt_bytes(raw)


def extract_text(file_path: str) -> str:
    """按扩展名抽取合同纯文本。自动处理加密/明文两种存储模式。"""
    data = _read_decrypted(file_path)
    lower = file_path.lower()
    if lower.endswith(".pdf"):
        return _extract_pdf_bytes(data)
    if lower.endswith(".docx"):
        return _extract_docx_bytes(data)
    if lower.endswith(".txt"):
        return data.decode("utf-8", errors="ignore")
    raise ValueError(f"不支持的文件类型: {file_path}")


def _is_garbled(text: str) -> bool:
    """检测文本是否乱码：CJK 字符占比低于 10% 且文本非空视为字体编码异常。"""
    if not text or len(text) < 20:
        return False  # 空文本交给 empty 逻辑处理，不走此判断
    cjk = sum(1 for c in text if '一' <= c <= '鿿')
    return cjk / len(text) < 0.10


def _extract_pdf_bytes(data: bytes) -> str:
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

    # 第二步：乱码检测 → PyMuPDF 降级
    if _is_garbled(text):
        log.info("parser.pdf_garbled", hint="检测到字体编码异常，切换 PyMuPDF 重新提取")
        text = _extract_pdf_pymupdf(data)

    if not text:
        log.warning("parser.pdf_empty", hint="文本层为空，可能是扫描件，需 OCR（路线图 P2）")
    return text


def _extract_pdf_pymupdf(data: bytes) -> str:
    """使用 PyMuPDF(fitz) 提取文本，对自定义字体无 ToUnicode 映射的 PDF 兜底更好。"""
    try:
        import fitz  # pymupdf

        doc = fitz.open(stream=data, filetype="pdf")
        parts: list[str] = []
        for page in doc:
            parts.append(page.get_text("text") or "")
        doc.close()
        text = "\n".join(parts).strip()
        if text:
            log.info("parser.pymupdf_ok", chars=len(text))
        return text
    except Exception as e:
        log.warning("parser.pymupdf_error", error=str(e))
        return ""


def _extract_docx_bytes(data: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs).strip()



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
    log.info("parser.elements", extracted={k: v for k, v in elements.items() if v})
    return elements
