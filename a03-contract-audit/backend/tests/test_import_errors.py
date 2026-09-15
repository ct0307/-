"""导入解析失败的稳定错误目录测试。"""

import pytest

from app.services.imports.errors import failure_for_code, parse_failure, pdf_text_empty_failure
from app.services.parser.ocr import OCRError, OCRLimitExceeded, OCRTimeout, OCRUnavailable


@pytest.mark.parametrize(
    ("exc", "code", "status", "retryable", "action"),
    [
        (OCRUnavailable("C:/secret/models/ocr missing"), "OCR_UNAVAILABLE", 503, True, "联系管理员修复后重试"),
        (OCRTimeout("C:/secret/contracts/timeout.pdf"), "OCR_TIMEOUT", 503, True, "稍后重试或拆分文件"),
        (OCRLimitExceeded("C:/secret/contracts/large.pdf"), "OCR_LIMIT_EXCEEDED", 422, False, "拆分或压缩文件后重试"),
        (OCRError("C:/secret/third-party response"), "OCR_PROTOCOL_ERROR", 503, True, "稍后重试"),
        (UnicodeError("C:/secret/contracts/encoding.pdf"), "PDF_TEXT_ENCODING_ERROR", 422, False, "重新导出 PDF 后重试"),
        (RuntimeError("C:/secret/contracts/missing.pdf"), "PARSE_INTERNAL_ERROR", 500, True, "稍后重试"),
    ],
)
def test_parse_failure_maps_exception_to_sanitized_stable_metadata(exc, code, status, retryable, action):
    failure = parse_failure(exc)

    assert failure.code == code
    assert failure.http_status == status
    assert failure.retryable is retryable
    assert failure.action == action
    assert "secret" not in failure.message.lower()
    assert "pdf" not in failure.message.lower() or code == "PDF_TEXT_ENCODING_ERROR"
    assert "missing.pdf" not in failure.message


def test_failure_for_code_only_returns_known_stable_metadata():
    failure = failure_for_code("OCR_TIMEOUT")

    assert failure is not None
    assert failure.code == "OCR_TIMEOUT"
    assert failure.retryable is True
    assert failure_for_code("LEGACY_UNKNOWN_CODE") is None


def test_pdf_text_empty_failure_is_non_retryable_and_safe():
    failure = pdf_text_empty_failure()

    assert failure.code == "PDF_TEXT_EMPTY"
    assert failure.http_status == 422
    assert failure.retryable is False
    assert failure.action == "重新导出 PDF 后重试"
