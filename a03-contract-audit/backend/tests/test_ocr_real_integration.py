"""真实 RapidOCR/ONNX Runtime 集成烟雾测试。"""
from __future__ import annotations

from io import BytesIO

import fitz
import pytest

pytest.importorskip("rapidocr", reason="未安装 RapidOCR，跳过真实引擎集成测试")

from PIL import Image, ImageDraw, ImageFont

from app.services.parser.ocr import RapidOCREngine, ocr_pdf_bytes


def _font() -> ImageFont.FreeTypeFont:
    candidates = (
        "DejaVuSans.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, 64)
        except OSError:
            continue
    pytest.skip("未找到可生成 OCR 烟雾样本的 TrueType 字体")


def _scan_png() -> bytes:
    image = Image.new("RGB", (1200, 260), "white")
    ImageDraw.Draw(image).text((60, 80), "CONTRACT 10000", fill="black", font=_font())
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _scan_pdf(png: bytes) -> bytes:
    document = fitz.open()
    page = document.new_page(width=600, height=130)
    page.insert_image(page.rect, stream=png)
    data = document.tobytes()
    document.close()
    return data


def test_real_rapidocr_recognizes_image_and_scanned_pdf():
    png = _scan_png()
    engine = RapidOCREngine()

    image_text, image_confidence = engine.recognize(png)
    pdf_result = ocr_pdf_bytes(
        _scan_pdf(png),
        dpi=180,
        min_confidence=0.0,
    )

    assert "CONTRACT" in image_text.upper()
    assert image_confidence > 0
    assert pdf_result.page_count == 1
    assert "CONTRACT" in pdf_result.text.upper()
    assert pdf_result.mean_confidence > 0
