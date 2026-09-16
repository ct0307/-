"""合同解析器的企业级降级契约。"""
from contextlib import nullcontext
from io import BytesIO
import time

import pdfplumber
import pytest

from app.services.parser import extractor
from app.services.parser.extractor import DocumentParseResult
from app.services.parser.ocr import OCRLimitExceeded, OCRResult, OCRTimeout, ocr_pdf_bytes


def _docx_bytes_with_interleaved_content() -> bytes:
    from docx import Document

    document = Document()
    document.add_paragraph("第一条 合同主体")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "甲方"
    table.cell(0, 1).text = "测试公司"
    document.add_paragraph("第二条 付款安排")
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _docx_bytes_with_image(
    *,
    image_size: tuple[int, int] | None = None,
    text: str = "",
) -> bytes:
    from docx import Document
    from docx.shared import Inches
    from PIL import Image

    document = Document()
    if text:
        document.add_paragraph(text)
    if image_size is not None:
        image_stream = BytesIO()
        Image.new("RGB", image_size, "white").save(image_stream, format="PNG")
        image_stream.seek(0)
        document.add_picture(image_stream, width=Inches(6))
    output = BytesIO()
    document.save(output)
    return output.getvalue()


class _EmptyPage:
    def extract_text(self) -> str:
        return ""


class _EmptyPdf:
    pages = [_EmptyPage()]


class _TextPage:
    def __init__(self, text: str) -> None:
        self.text = text

    def extract_text(self) -> str:
        return self.text


def test_docx_preserves_paragraph_and_table_order_with_blocks():
    result = extractor._extract_docx_result(_docx_bytes_with_interleaved_content())

    assert result.text.splitlines() == [
        "第一条 合同主体",
        "甲方  测试公司",
        "第二条 付款安排",
    ]
    assert [block.block_type for block in result.blocks] == [
        "paragraph",
        "table_row",
        "paragraph",
    ]
    assert result.blocks[0].anchor.paragraph_index == 0
    assert result.blocks[1].anchor.table_index == 0
    assert result.blocks[1].anchor.row_index == 0


def test_image_only_docx_requires_manual_review():
    result = extractor._extract_docx_result(
        _docx_bytes_with_image(image_size=(1600, 2200))
    )

    assert result.requires_review is True
    assert result.review_reason == "DOCX 疑似图片型文档，未提取到足够正文"


def test_docx_with_normal_text_and_small_logo_does_not_require_review():
    text = "合同正文包含双方主体、服务内容、付款安排和违约责任。" * 12

    result = extractor._extract_docx_result(
        _docx_bytes_with_image(image_size=(300, 100), text=text)
    )

    assert result.text == text
    assert result.requires_review is False
    assert result.review_reason is None


def test_empty_docx_requires_manual_review_with_distinct_reason():
    result = extractor._extract_docx_result(_docx_bytes_with_image())

    assert result.requires_review is True
    assert result.review_reason == "DOCX 正文为空"


def test_pdf_exposes_page_numbered_blocks(monkeypatch):
    monkeypatch.setattr(
        pdfplumber,
        "open",
        lambda _: _pdf_with_pages("第一页付款条款", "第二页违约责任"),
    )

    result = extractor._extract_pdf_result(b"text-pdf")

    assert [block.text for block in result.blocks] == ["第一页付款条款", "第二页违约责任"]
    assert [block.anchor.page_number for block in result.blocks] == [1, 2]
    assert all(block.block_type == "page_text" for block in result.blocks)


def test_pdf_uses_word_coordinates_for_precise_line_blocks(monkeypatch):
    class PositionedPage:
        width = 600
        height = 800

        def extract_text(self) -> str:
            return "第一条 付款安排\n验收后十日付款"

        def extract_words(self, **_kwargs):
            return [
                {"text": "第一条", "x0": 72, "top": 100, "x1": 112, "bottom": 115},
                {"text": "付款安排", "x0": 120, "top": 100, "x1": 180, "bottom": 115},
                {"text": "验收后十日付款", "x0": 72, "top": 130, "x1": 180, "bottom": 145},
            ]

    monkeypatch.setattr(
        pdfplumber,
        "open",
        lambda _: nullcontext(type("Pdf", (), {"pages": [PositionedPage()]})()),
    )

    result = extractor._extract_pdf_result(b"positioned-pdf")

    assert [block.text for block in result.blocks] == ["第一条 付款安排", "验收后十日付款"]
    assert result.blocks[0].anchor.page_number == 1
    assert result.blocks[0].anchor.bbox == (72.0, 100.0, 180.0, 115.0)


def _pdf_with_pages(*texts: str):
    return nullcontext(type("Pdf", (), {"pages": [_TextPage(text) for text in texts]})())


def _pymupdf_candidate(*texts: str):
    return extractor._PDFTextCandidate("\n".join(texts).strip(), texts)


def test_compatibility_radical_detection_uses_count_and_ratio_thresholds():
    assert extractor._compatibility_radical_count("合同⾃⼰⼈") == 3
    assert extractor._has_suspicious_radicals("合同正文⾃⼰⼈") is True
    assert extractor._has_suspicious_radicals("正常合同中的单个字符" * 20 + "⾃") is False
    assert extractor._has_suspicious_radicals("甲⾃") is True
    assert extractor._compatibility_radical_count("甲方⿰乙方") == 0


def test_prefer_pymupdf_text_requires_a_clean_complete_quality_improvement():
    primary = "甲方⾃⼰⼈签订合同" * 10
    clean = "甲方自己人签订合同" * 10

    assert extractor._prefer_pymupdf_text(primary, clean) is True
    assert extractor._prefer_pymupdf_text(primary, "正常中文") is False
    assert extractor._prefer_pymupdf_text(primary, "甲方⾃⼰签订合同" * 10) is False
    assert extractor._prefer_pymupdf_text(primary, "plain contract text" * 10) is False


def test_normalize_compatibility_radicals_only_normalizes_target_range():
    assert extractor._normalize_compatibility_radicals("合同⾃⼰⼈⿰") == "合同自己人⿰"


def test_pdf_prefers_clean_pymupdf_candidate_for_compatibility_radicals(monkeypatch):
    primary = "甲方⾃⼰⼈签订合同" * 10
    alternate = "甲方自己人签订合同" * 10
    monkeypatch.setattr(pdfplumber, "open", lambda _: _pdf_with_pages(primary))
    monkeypatch.setattr(
        extractor,
        "_extract_pdf_pymupdf_candidate",
        lambda _data, expected_pages=None: _pymupdf_candidate(alternate),
    )

    result = extractor._extract_pdf_result(b"pdf")

    assert result.text == alternate
    assert "⾃" not in result.text


@pytest.mark.parametrize(
    "alternate",
    [
        "正常中文",
        "甲方⾃⼰签订合同" * 10,
    ],
)
def test_pdf_keeps_primary_and_normalizes_radicals_for_low_quality_candidate(
    monkeypatch,
    alternate,
):
    primary = "甲方⾃⼰⼈签订合同" * 10
    monkeypatch.setattr(pdfplumber, "open", lambda _: _pdf_with_pages(primary))
    monkeypatch.setattr(
        extractor,
        "_extract_pdf_pymupdf_candidate",
        lambda _data, expected_pages=None: _pymupdf_candidate(alternate),
    )

    result = extractor._extract_pdf_result(b"pdf")

    assert result.text == "甲方自己人签订合同" * 10


def test_pdf_does_not_bypass_quality_gate_after_radical_normalization(monkeypatch):
    primary = "contract text " * 100 + "⾃⼰⼈"
    calls = 0

    monkeypatch.setattr(pdfplumber, "open", lambda _: _pdf_with_pages(primary))

    def short_candidate(_data, expected_pages=None):
        nonlocal calls
        calls += 1
        return "正常中文"

    monkeypatch.setattr(
        extractor,
        "_extract_pdf_pymupdf_candidate",
        lambda data, expected_pages=None: _pymupdf_candidate(
            short_candidate(data, expected_pages)
        ),
    )

    result = extractor._extract_pdf_result(b"pdf")

    assert result.text == "contract text " * 100 + "自己人"
    assert calls == 1


def test_pdf_with_radicals_and_empty_page_still_uses_ocr(monkeypatch):
    primary = "第一页⾃⼰⼈合同" * 10
    alternate = "第一页自己人合同" * 10 + "第二页正常文字"
    monkeypatch.setattr(pdfplumber, "open", lambda _: _pdf_with_pages(primary, ""))
    monkeypatch.setattr(
        extractor,
        "_extract_pdf_pymupdf_candidate",
        lambda _data, expected_pages=None: _pymupdf_candidate(alternate, ""),
    )
    monkeypatch.setattr(
        extractor,
        "ocr_pdf_bytes",
        lambda *_args, **_kwargs: OCRResult(
            text="第二页扫描文字",
            page_count=1,
            mean_confidence=0.93,
            page_texts=("第二页扫描文字",),
        ),
    )

    result = extractor._extract_pdf_result(b"pdf")

    assert result.source == "mixed"
    assert "第一页自己人合同" in result.text
    assert "第二页扫描文字" in result.text


def test_pdf_rejects_candidate_when_corresponding_nonempty_page_is_empty(monkeypatch):
    primary_pages = ("第一页⾃⼰⼈合同" * 20, "第二页合同正文")
    alternate_first_page = "第一页自己人合同" * 20
    monkeypatch.setattr(pdfplumber, "open", lambda _: _pdf_with_pages(*primary_pages))
    monkeypatch.setattr(
        extractor,
        "_extract_pdf_pymupdf_candidate",
        lambda _data, expected_pages=None: _pymupdf_candidate(alternate_first_page, ""),
    )

    result = extractor._extract_pdf_result(b"pdf")

    assert "第一页自己人合同" in result.text
    assert "第二页合同正文" in result.text


def test_pdf_rejects_candidate_when_one_page_is_below_length_threshold(monkeypatch):
    primary_pages = ("第一页⾃⼰⼈合同" * 100, "第二页合同正文" * 10)
    alternate_pages = ("第一页自己人合同" * 100, "字")
    monkeypatch.setattr(pdfplumber, "open", lambda _: _pdf_with_pages(*primary_pages))
    monkeypatch.setattr(
        extractor,
        "_extract_pdf_pymupdf_candidate",
        lambda _data, expected_pages=None: _pymupdf_candidate(*alternate_pages),
    )

    result = extractor._extract_pdf_result(b"pdf")

    assert "第一页自己人合同" in result.text
    assert "第二页合同正文" * 10 in result.text


def test_pdf_does_not_try_fallback_for_one_compatibility_radical(monkeypatch):
    primary = "这是完整合同正文" * 30 + "⾃"
    monkeypatch.setattr(pdfplumber, "open", lambda _: _pdf_with_pages(primary))
    monkeypatch.setattr(
        extractor,
        "_extract_pdf_pymupdf_candidate",
        lambda *_args, **_kwargs: pytest.fail("单个兼容部首不应触发 PyMuPDF 回退"),
    )

    result = extractor._extract_pdf_result(b"pdf")

    assert result.text == primary


def test_pdf_rejects_pymupdf_candidate_with_incomplete_page_count(monkeypatch):
    primary_pages = ("第一页⾃⼰⼈合同" * 10, "第二页合同正文" * 10)
    monkeypatch.setattr(pdfplumber, "open", lambda _: _pdf_with_pages(*primary_pages))

    def incomplete_candidate(_data, expected_pages=None):
        assert expected_pages == 2
        return ""

    monkeypatch.setattr(
        extractor,
        "_extract_pdf_pymupdf_candidate",
        lambda data, expected_pages=None: _pymupdf_candidate(
            incomplete_candidate(data, expected_pages)
        ),
    )

    result = extractor._extract_pdf_result(b"pdf")

    assert "第一页自己人合同" in result.text
    assert "第二页合同正文" in result.text


def test_pymupdf_candidate_closes_document_when_page_extraction_fails(monkeypatch):
    import fitz

    class BrokenPage:
        def get_text(self, _mode):
            raise RuntimeError("extract failed")

    class FakeDocument:
        closed = False

        def __iter__(self):
            return iter((BrokenPage(),))

        def __len__(self):
            return 1

        def close(self):
            self.closed = True

    document = FakeDocument()
    monkeypatch.setattr(fitz, "open", lambda **_kwargs: document)

    result = extractor._extract_pdf_pymupdf_candidate(b"pdf", expected_pages=1)

    assert result.text == ""
    assert document.closed is True


def test_elements_log_contains_keys_not_contract_values(monkeypatch):
    captured: dict = {}
    sensitive_value = "敏感公司"
    monkeypatch.setattr(
        extractor.log,
        "info",
        lambda event, **kwargs: captured.update(event=event, **kwargs),
    )

    extractor.extract_elements(f"甲方：{sensitive_value}\n合同正文")

    assert captured["event"] == "parser.elements"
    assert sensitive_value not in repr(captured)
    assert "extracted" not in captured
    assert set(captured) == {
        "event",
        "fields",
        "field_count",
        "text_length",
        "has_breach_clause",
        "has_dispute_clause",
    }


def test_flat_extract_elements_keeps_payment_terms_as_legacy_string():
    result = extractor.extract_elements(
        "付款安排：\n1. 签订后支付30%；\n2. 验收后支付70%。"
    )

    assert result["payment_terms"] == "签订后支付30%；验收后支付70%"


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


def test_ocr_marks_review_when_any_page_is_below_confidence_threshold():
    confidences = iter((0.9, 0.6))

    result = ocr_pdf_bytes(
        _blank_pdf(2),
        engine=lambda _image: ("识别文本", next(confidences)),
        min_confidence=0.75,
    )

    assert result.mean_confidence == pytest.approx(0.75)
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
