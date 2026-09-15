"""合同解析失败的稳定、脱敏错误目录。"""

from dataclasses import dataclass

from app.services.parser.ocr import OCRError, OCRLimitExceeded, OCRTimeout, OCRUnavailable


@dataclass(frozen=True)
class ImportFailure:
    code: str
    message: str
    action: str
    retryable: bool
    http_status: int


PDF_TEXT_EMPTY = ImportFailure(
    code="PDF_TEXT_EMPTY",
    message="未能从文件中提取有效文本，请重新导出 PDF 后重试",
    action="重新导出 PDF 后重试",
    retryable=False,
    http_status=422,
)
PDF_TEXT_ENCODING_ERROR = ImportFailure(
    code="PDF_TEXT_ENCODING_ERROR",
    message="PDF 文本编码异常，请重新导出 PDF 后重试",
    action="重新导出 PDF 后重试",
    retryable=False,
    http_status=422,
)
OCR_UNAVAILABLE = ImportFailure(
    code="OCR_UNAVAILABLE",
    message="OCR 服务暂不可用，请联系管理员修复后重试",
    action="联系管理员修复后重试",
    retryable=True,
    http_status=503,
)
OCR_TIMEOUT = ImportFailure(
    code="OCR_TIMEOUT",
    message="OCR 处理超时，请稍后重试或拆分文件",
    action="稍后重试或拆分文件",
    retryable=True,
    http_status=503,
)
OCR_LIMIT_EXCEEDED = ImportFailure(
    code="OCR_LIMIT_EXCEEDED",
    message="文件超出 OCR 处理限制，请拆分或压缩文件后重试",
    action="拆分或压缩文件后重试",
    retryable=False,
    http_status=422,
)
OCR_PROTOCOL_ERROR = ImportFailure(
    code="OCR_PROTOCOL_ERROR",
    message="OCR 服务响应异常，请稍后重试",
    action="稍后重试",
    retryable=True,
    http_status=503,
)
PARSE_INTERNAL_ERROR = ImportFailure(
    code="PARSE_INTERNAL_ERROR",
    message="合同解析失败，请稍后重试",
    action="稍后重试",
    retryable=True,
    http_status=500,
)

_FAILURES_BY_CODE = {
    failure.code: failure
    for failure in (
        PDF_TEXT_EMPTY,
        PDF_TEXT_ENCODING_ERROR,
        OCR_UNAVAILABLE,
        OCR_TIMEOUT,
        OCR_LIMIT_EXCEEDED,
        OCR_PROTOCOL_ERROR,
        PARSE_INTERNAL_ERROR,
    )
}


def pdf_text_empty_failure() -> ImportFailure:
    return PDF_TEXT_EMPTY


def failure_for_code(code: str | None) -> ImportFailure | None:
    return _FAILURES_BY_CODE.get(code)


def parse_failure(exc: Exception) -> ImportFailure:
    if isinstance(exc, OCRUnavailable):
        return OCR_UNAVAILABLE
    if isinstance(exc, OCRTimeout):
        return OCR_TIMEOUT
    if isinstance(exc, OCRLimitExceeded):
        return OCR_LIMIT_EXCEEDED
    if isinstance(exc, OCRError):
        return OCR_PROTOCOL_ERROR
    if isinstance(exc, UnicodeError):
        return PDF_TEXT_ENCODING_ERROR
    return PARSE_INTERNAL_ERROR
