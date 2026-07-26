"""合同解析器的企业级降级契约。"""
from contextlib import nullcontext
import time

import pdfplumber
import pytest

from app.services.parser import extractor
from app.services.parser.extractor import DocumentParseResult
from app.services.parser.ocr import OCRLimitExceeded, OCRResult, OCRTimeout, ocr_pdf_bytes


class _EmptyPage:
    def extract_text(self) -> str:
        return ""


class _EmptyPdf:
    pages = [_EmptyPage()]


def test_text_pdf_returns_native_parse_result(monkeypatch):
    class TextPage:
        def extract_text(self) -> str:
            return "甲方：测试公司\n乙方：交付公司\n" + "合同正文" * 60

    monkeypatch.setattr(
        pdfplumber,
        "open",
        lambda _: nullcontext(type("Pdf", (), {"pages": [TextPage()]})()),
    )

    result = extractor._extract_pdf_result(b"text-pdf")

    assert isinstance(result, DocumentParseResult)
    assert result.source == "native"
    assert result.ocr_confidence is None
    assert result.requires_review is False


def test_mixed_pdf_preserves_low_ocr_confidence(monkeypatch):
    class TextPage:
        def extract_text(self) -> str:
            return "正常文字页" * 60

    monkeypatch.setattr(
        pdfplumber,
        "open",
        lambda _: nullcontext(type("Pdf", (), {"pages": [TextPage(), _EmptyPage()]})()),
    )
    monkeypatch.setattr(
        extractor,
        "ocr_pdf_bytes",
        lambda *_args, **_kwargs: OCRResult(
            text="低置信度扫描页",
            page_count=1,
            mean_confidence=0.41,
            page_texts=("低置信度扫描页",),
            requires_review=True,
        ),
    )

    result = extractor._extract_pdf_result(b"mixed-pdf")

    assert result.source == "mixed"
    assert result.ocr_confidence == 0.41
    assert result.requires_review is True
    assert result.review_reason == "OCR 平均置信度低于 75%"


def test_scanned_pdf_uses_ocr_when_text_extractors_are_empty(monkeypatch):
    """文本层和 PyMuPDF 均为空时必须进入 OCR，不能静默返回空文本。"""
    monkeypatch.setattr(pdfplumber, "open", lambda _: nullcontext(_EmptyPdf()))
    monkeypatch.setattr(extractor, "_extract_pdf_pymupdf", lambda _: "")
    monkeypatch.setattr(extractor, "ocr_pdf_bytes", lambda _data, **_kwargs: "甲方：测试公司", raising=False)

    assert extractor._extract_pdf_bytes(b"scanned-pdf") == "甲方：测试公司"


def test_text_pdf_does_not_invoke_ocr(monkeypatch):
    class TextPage:
        def extract_text(self) -> str:
            return "甲方：测试公司\n乙方：交付公司\n合同正文内容完整。"

    monkeypatch.setattr(pdfplumber, "open", lambda _: nullcontext(type("Pdf", (), {"pages": [TextPage()]})()))
    monkeypatch.setattr(
        extractor,
        "ocr_pdf_bytes",
        lambda *_args, **_kwargs: pytest.fail("文本型 PDF 不应触发 OCR"),
        raising=False,
    )

    assert "测试公司" in extractor._extract_pdf_bytes(b"text-pdf")


def test_mixed_pdf_ocr_fills_empty_pages(monkeypatch):
    class TextPage:
        def extract_text(self) -> str:
            return "第一页合同正文，甲方为测试公司，乙方为交付公司。"

    monkeypatch.setattr(
        pdfplumber,
        "open",
        lambda _: nullcontext(type("Pdf", (), {"pages": [TextPage(), _EmptyPage()]})()),
    )
    monkeypatch.setattr(
        extractor,
        "ocr_pdf_bytes",
        lambda _data, **_kwargs: OCRResult(
            text="第二页扫描付款条款",
            page_count=1,
            mean_confidence=0.92,
            page_texts=("第二页扫描付款条款",),
        ),
        raising=False,
    )

    text = extractor._extract_pdf_bytes(b"mixed-pdf")

    assert "第一页合同正文" in text
    assert "第二页扫描付款条款" in text


def _blank_pdf(page_count: int) -> bytes:
    import fitz

    document = fitz.open()
    for _ in range(page_count):
        document.new_page(width=200, height=200)
    data = document.tobytes()
    document.close()
    return data


def test_ocr_rejects_pdf_over_page_limit():
    with pytest.raises(OCRLimitExceeded):
        ocr_pdf_bytes(_blank_pdf(2), engine=lambda _image: ("文本", 0.9), max_pages=1)


def test_ocr_marks_low_confidence_for_manual_review():
    result = ocr_pdf_bytes(
        _blank_pdf(1),
        engine=lambda _image: ("低置信度文本", 0.42),
        min_confidence=0.75,
    )

    assert result.text == "低置信度文本"
    assert result.requires_review is True


def test_ocr_only_renders_requested_pages():
    recognized: list[bytes] = []

    result = ocr_pdf_bytes(
        _blank_pdf(2),
        engine=lambda image: (recognized.append(image) or "第二页文本", 0.91),
        page_indices=(1,),
    )

    assert result.page_count == 1
    assert result.page_texts == ("第二页文本",)
    assert len(recognized) == 1


def test_ocr_rejects_page_over_pixel_limit():
    with pytest.raises(OCRLimitExceeded, match="像素"):
        ocr_pdf_bytes(
            _blank_pdf(1),
            engine=lambda _image: ("文本", 0.9),
            dpi=72,
            max_page_pixels=39_999,
        )


def test_ocr_stops_after_total_timeout():
    def slow_engine(_image: bytes) -> tuple[str, float]:
        time.sleep(0.01)
        return "文本", 0.9

    with pytest.raises(OCRTimeout):
        ocr_pdf_bytes(_blank_pdf(1), engine=slow_engine, timeout_seconds=0.001)
