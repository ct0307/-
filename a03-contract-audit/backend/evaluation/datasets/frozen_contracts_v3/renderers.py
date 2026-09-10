"""使用自然流式分页渲染 v3 DOCX、文本 PDF 和扫描 PDF。"""
from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path

import fitz
from docx import Document as WordDocument
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor
from PIL import Image, ImageDraw, ImageEnhance

from .content import ContractDocument, ContractSection
from .models import ContractCase
from .ooxml import inject_revisions


A4 = fitz.paper_rect("a4")
MARGIN_X = 50.0
TOP = 52.0
BOTTOM = 48.0
MIN_ANNEX_START_SPACE = 290.0


def resolve_cjk_font() -> Path:
    for value in (os.getenv("CONTRACT_TEST_FONT"), "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simsun.ttc"):
        if value and Path(value).is_file():
            return Path(value)
    raise RuntimeError("未找到中文字体，请设置 CONTRACT_TEST_FONT")


def _east_asia(run, name: str, size: float, bold: bool = False) -> None:
    run.font.name = name
    run.font.size = Pt(size)
    run.bold = bold
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), name)


def _page_number(paragraph) -> None:
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run("第 ")
    _east_asia(run, "微软雅黑", 8)
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instruction = OxmlElement("w:instrText")
    instruction.set(qn("xml:space"), "preserve")
    instruction.text = " PAGE "
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.extend((begin, instruction, end))
    _east_asia(paragraph.add_run(" 页"), "微软雅黑", 8)


def _word_paragraph(container, text: str, size: float = 10.5, bold: bool = False):
    paragraph = container.add_paragraph()
    paragraph.paragraph_format.space_after = Pt(4)
    paragraph.paragraph_format.line_spacing = 1.35
    if not bold:
        paragraph.paragraph_format.first_line_indent = Mm(7.4)
    _east_asia(paragraph.add_run(text), "宋体", size, bold)
    return paragraph


def _word_table(container, rows: tuple[tuple[str, ...], ...]) -> None:
    if not rows:
        return
    table = container.add_table(rows=0, cols=max(len(row) for row in rows))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for row_index, values in enumerate(rows):
        cells = table.add_row().cells
        for index, cell in enumerate(cells):
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            value = values[index] if index < len(values) else ""
            paragraph = cell.paragraphs[0]
            _east_asia(paragraph.add_run(value), "宋体", 8.5, row_index == 0)
            if row_index == 0:
                shading = OxmlElement("w:shd")
                shading.set(qn("w:fill"), "E7E6E6")
                cell._tc.get_or_add_tcPr().append(shading)


def render_docx(document: ContractDocument, output_path: Path, *, case: ContractCase) -> Path:
    path = Path(output_path)
    if path.suffix.lower() != ".docx":
        raise ValueError("DOCX 输出必须使用 .docx 扩展名")
    path.parent.mkdir(parents=True, exist_ok=True)
    word = WordDocument()
    section = word.sections[0]
    section.page_width, section.page_height = Mm(210), Mm(297)
    section.top_margin, section.bottom_margin = Mm(22), Mm(20)
    section.left_margin, section.right_margin = Mm(22), Mm(22)
    section.header.paragraphs[0].text = f"{document.case_id}  合成验收样本"
    _page_number(section.footer.paragraphs[0])

    marker = word.add_paragraph()
    marker.alignment = WD_ALIGN_PARAGRAPH.CENTER
    marker_run = marker.add_run(document.header_lines[0])
    _east_asia(marker_run, "微软雅黑", 10, True)
    marker_run.font.color.rgb = RGBColor(192, 0, 0)
    title = word.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_before = Pt(72)
    title.paragraph_format.space_after = Pt(26)
    _east_asia(title.add_run(document.title), "微软雅黑", 22, True)
    for line in document.header_lines[1:]:
        paragraph = word.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _east_asia(paragraph.add_run(line), "宋体", 11)
    word.add_page_break()
    for item in document.sections:
        heading = _word_paragraph(word, item.heading, 12, True)
        heading.paragraph_format.keep_with_next = True
        for paragraph in item.paragraphs:
            _word_paragraph(word, paragraph)
        _word_table(word, item.rows)
    for index, item in enumerate(document.annexes):
        if index == 0:
            word.add_page_break()
        heading = _word_paragraph(word, item.heading, 14, True)
        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for paragraph in item.paragraphs:
            _word_paragraph(word, paragraph)
        _word_table(word, item.rows)
    word.core_properties.title = document.title
    word.core_properties.subject = "合成测试合同，仅用于系统验收"
    word.core_properties.author = "合同审查系统测试生成器"
    word.save(path)
    if case.revision_set is not None:
        inject_revisions(path, case.revision_set)
    return path


def _wrap(font: fitz.Font, text: str, width: float, size: float) -> list[str]:
    lines: list[str] = []
    for source in text.splitlines() or [""]:
        current = ""
        for character in source:
            candidate = current + character
            if current and font.text_length(candidate, fontsize=size) > width:
                lines.append(current)
                current = character
            else:
                current = candidate
        lines.append(current)
    return lines


class _PdfFlow:
    def __init__(self, document: ContractDocument):
        self.document = document
        self.font_path = resolve_cjk_font()
        self.font = fitz.Font(fontfile=str(self.font_path))
        self.pdf = fitz.open()
        self.page: fitz.Page | None = None
        self.y = TOP

    def new_page(self) -> None:
        self.page = self.pdf.new_page(width=A4.width, height=A4.height)
        self.page.insert_font(fontname="CJK", fontfile=str(self.font_path))
        self.y = TOP

    def ensure(self, height: float) -> None:
        if self.page is None or self.y + height > A4.height - BOTTOM:
            self.new_page()

    def lines_height(self, text: str, size: float, indent: float = 0, bold: bool = False) -> float:
        width = A4.width - 2 * MARGIN_X - indent
        line_count = len(_wrap(self.font, text, width, size))
        return line_count * size * 1.55 + (4 if bold else 2)

    def lines(self, text: str, size: float, indent: float = 0, bold: bool = False) -> None:
        width = A4.width - 2 * MARGIN_X - indent
        lines = _wrap(self.font, text, width, size)
        step = size * 1.55
        self.ensure(self.lines_height(text, size, indent, bold))
        assert self.page is not None
        for line in lines:
            self.page.insert_text((MARGIN_X + indent, self.y), line, fontname="CJK", fontsize=size, color=(0, 0, 0))
            self.y += step
        self.y += 4 if bold else 2

    def table(self, rows: tuple[tuple[str, ...], ...]) -> None:
        if not rows:
            return
        columns = max(len(row) for row in rows)
        table_width = A4.width - 2 * MARGIN_X
        column_width = table_width / columns
        for row_index, row in enumerate(rows):
            wrapped = [
                _wrap(self.font, row[column] if column < len(row) else "", column_width - 8, 7.5)
                for column in range(columns)
            ]
            row_height = max(22.0, max(len(lines) for lines in wrapped) * 10.2 + 8)
            self.ensure(row_height)
            assert self.page is not None
            for column, lines in enumerate(wrapped):
                x0 = MARGIN_X + column * column_width
                rect = fitz.Rect(x0, self.y, x0 + column_width, self.y + row_height)
                fill = (0.91, 0.92, 0.93) if row_index == 0 else None
                self.page.draw_rect(rect, color=(0.65, 0.65, 0.65), fill=fill, width=0.55)
                text_y = self.y + 11
                for line in lines:
                    self.page.insert_text((x0 + 4, text_y), line, fontname="CJK", fontsize=7.5)
                    text_y += 10.2
            self.y += row_height
        self.y += 8

    def section(self, item: ContractSection) -> None:
        start_height = self.lines_height(item.heading, 11.5, bold=True)
        if item.paragraphs:
            start_height += self.lines_height(item.paragraphs[0], 9.2, indent=14)
        self.ensure(start_height)
        self.lines(item.heading, 11.5, bold=True)
        for paragraph in item.paragraphs:
            self.lines(paragraph, 9.2, indent=14)
        self.table(item.rows)


def _text_pdf_bytes(document: ContractDocument) -> bytes:
    flow = _PdfFlow(document)
    flow.new_page()
    flow.y = 75
    flow.lines(document.header_lines[0], 11, indent=20, bold=True)
    flow.y = 220
    flow.lines(document.title, 22, indent=30, bold=True)
    for line in document.header_lines[1:]:
        flow.lines(line, 11, indent=45)
    flow.new_page()
    for item in document.sections:
        flow.section(item)
    for index, item in enumerate(document.annexes):
        remaining_height = A4.height - BOTTOM - flow.y
        if index == 0 or remaining_height < MIN_ANNEX_START_SPACE:
            flow.new_page()
        flow.section(item)
    for number, page in enumerate(flow.pdf, start=1):
        footer = f"{document.case_id}  第 {number} 页 / 共 {flow.pdf.page_count} 页"
        page.insert_text((MARGIN_X, A4.height - 22), footer, fontname="CJK", fontsize=7.5, color=(0.45, 0.45, 0.45))
    flow.pdf.set_metadata({"title": document.title, "author": "合同审查系统测试生成器", "subject": "合成测试合同"})
    flow.pdf.subset_fonts()
    data = flow.pdf.tobytes(garbage=4, deflate=True)
    flow.pdf.close()
    return data


def render_text_pdf(document: ContractDocument, output_path: Path) -> Path:
    path = Path(output_path)
    if path.suffix.lower() != ".pdf":
        raise ValueError("PDF 输出必须使用 .pdf 扩展名")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_text_pdf_bytes(document))
    return path


def _scanned_bytes(document: ContractDocument, mixed: bool) -> bytes:
    source = fitz.open(stream=_text_pdf_bytes(document), filetype="pdf")
    output = fitz.open()
    try:
        for index, source_page in enumerate(source):
            target = output.new_page(width=source_page.rect.width, height=source_page.rect.height)
            if mixed and index % 3 == 0:
                target.show_pdf_page(target.rect, source, index)
                continue
            pixmap = source_page.get_pixmap(dpi=120, alpha=False)
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            angle = 0.22 if index % 2 == 0 else -0.22
            image = image.rotate(angle, resample=Image.Resampling.BICUBIC, fillcolor=(248, 248, 245))
            image = ImageEnhance.Contrast(ImageEnhance.Brightness(image).enhance(0.985)).enhance(0.97)
            draw = ImageDraw.Draw(image)
            for offset in range(6):
                shade = 210 + offset * 7
                draw.line((offset, 0, offset, image.height), fill=(shade, shade, shade))
            stream = BytesIO()
            image.save(stream, format="JPEG", quality=84, optimize=True)
            target.insert_image(target.rect, stream=stream.getvalue())
        return output.tobytes(garbage=4, deflate=True)
    finally:
        output.close()
        source.close()


def render_scanned_pdf(document: ContractDocument, output_path: Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_scanned_bytes(document, mixed=False))
    return path


def render_mixed_pdf(document: ContractDocument, output_path: Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_scanned_bytes(document, mixed=True))
    return path
