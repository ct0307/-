"""确定性渲染 DOCX、文本 PDF、扫描 PDF 和混合 PDF。"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import math
import os
from pathlib import Path

import fitz
from docx import Document as WordDocument
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor
from PIL import Image, ImageDraw, ImageEnhance

from .content import ContractDocument, ContractSection


A4_RECT = fitz.paper_rect("a4")
PDF_MARGIN_X = 50.0
PDF_TOP = 48.0
PDF_BOTTOM = 46.0


@dataclass(frozen=True)
class ScanProfile:
    dpi: int
    rotation_degrees: float
    brightness: float
    contrast: float
    jpeg_quality: int
    shadow_width: int

    @classmethod
    def light(cls) -> "ScanProfile":
        return cls(
            dpi=120,
            rotation_degrees=0.28,
            brightness=0.98,
            contrast=0.96,
            jpeg_quality=82,
            shadow_width=8,
        )


@dataclass(frozen=True)
class _RenderBlock:
    heading: str
    paragraphs: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...] = ()


def resolve_cjk_font() -> Path:
    candidates = (
        os.getenv("CONTRACT_TEST_FONT"),
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simsun.ttc",
    )
    for value in candidates:
        if value and Path(value).is_file():
            return Path(value)
    raise RuntimeError("未找到可嵌入的中文字体，请设置 CONTRACT_TEST_FONT")


def _split_section(section: ContractSection) -> tuple[_RenderBlock, ...]:
    if len(section.rows) <= 5:
        return (_RenderBlock(section.heading, section.paragraphs, section.rows),)

    header = section.rows[:1]
    body = section.rows[1:]
    chunks = tuple(body[index : index + 4] for index in range(0, len(body), 4))
    return tuple(
        _RenderBlock(
            section.heading if index == 0 else f"{section.heading}（续）",
            section.paragraphs if index == 0 else (),
            header + chunk,
        )
        for index, chunk in enumerate(chunks)
    )


def _render_blocks(document: ContractDocument) -> tuple[_RenderBlock, ...]:
    blocks: list[_RenderBlock] = []
    for section in (*document.sections, *document.annexes):
        blocks.extend(_split_section(section))
    return tuple(blocks)


def _block_weight(block: _RenderBlock) -> int:
    text_chars = len(block.heading) + sum(len(item) for item in block.paragraphs)
    row_chars = sum(sum(len(cell) for cell in row) for row in block.rows)
    return max(2, math.ceil(text_chars / 42) + math.ceil(row_chars / 34) + len(block.rows))


def _partition_blocks(
    blocks: tuple[_RenderBlock, ...],
    page_count: int,
) -> tuple[tuple[_RenderBlock, ...], ...]:
    if page_count <= 0:
        raise ValueError("内容页数必须大于 0")
    if len(blocks) < page_count:
        raise ValueError("有效内容不足，无法在不插入空白页的情况下达到目标页数")

    pages: list[tuple[_RenderBlock, ...]] = []
    cursor = 0
    remaining_weight = sum(_block_weight(block) for block in blocks)
    for page_index in range(page_count):
        pages_left = page_count - page_index
        blocks_left = len(blocks) - cursor
        if pages_left == 1:
            pages.append(blocks[cursor:])
            break

        target = remaining_weight / pages_left
        current: list[_RenderBlock] = []
        current_weight = 0
        while blocks_left > pages_left:
            candidate = blocks[cursor]
            candidate_weight = _block_weight(candidate)
            if current and current_weight + candidate_weight > target * 1.05:
                break
            current.append(candidate)
            current_weight += candidate_weight
            cursor += 1
            blocks_left -= 1
        if not current:
            current.append(blocks[cursor])
            current_weight = _block_weight(blocks[cursor])
            cursor += 1
        pages.append(tuple(current))
        remaining_weight -= current_weight
    return tuple(pages)


def paginate_document(
    document: ContractDocument,
) -> tuple[tuple[_RenderBlock, ...], ...]:
    """返回封面后的内容页分组；封面由渲染器单独生成。"""
    if document.target_pages < 2:
        raise ValueError("合同目标页数至少为 2")
    return _partition_blocks(_render_blocks(document), document.target_pages - 1)


def _set_east_asia_font(run, font_name: str, size: float, *, bold: bool = False) -> None:
    run.font.name = font_name
    run.font.size = Pt(size)
    run.bold = bold
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), font_name)


def _set_cell_shading(cell, fill: str) -> None:
    properties = cell._tc.get_or_add_tcPr()
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), fill)
    properties.append(shading)


def _add_page_number(paragraph) -> None:
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run("第 ")
    _set_east_asia_font(run, "微软雅黑", 8)
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instruction = OxmlElement("w:instrText")
    instruction.set(qn("xml:space"), "preserve")
    instruction.text = " PAGE "
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.extend((begin, instruction, separate, end))
    suffix = paragraph.add_run(" 页")
    _set_east_asia_font(suffix, "微软雅黑", 8)


def _word_paragraph(container, text: str, *, size: float = 10.5, bold: bool = False):
    paragraph = container.add_paragraph()
    paragraph.paragraph_format.space_after = Pt(5)
    paragraph.paragraph_format.line_spacing = 1.35
    paragraph.paragraph_format.first_line_indent = Mm(7.4) if not bold else None
    run = paragraph.add_run(text)
    _set_east_asia_font(run, "宋体", size, bold=bold)
    return paragraph


def _word_table(container, rows: tuple[tuple[str, ...], ...]) -> None:
    if not rows:
        return
    column_count = max(len(row) for row in rows)
    table = container.add_table(rows=0, cols=column_count)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    total_width = Mm(166)
    cell_width = int(total_width / column_count)
    for row_index, values in enumerate(rows):
        cells = table.add_row().cells
        for index, cell in enumerate(cells):
            cell.width = cell_width
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            if row_index == 0:
                _set_cell_shading(cell, "E7E6E6")
            paragraph = cell.paragraphs[0]
            paragraph.paragraph_format.space_after = Pt(0)
            value = values[index] if index < len(values) else ""
            run = paragraph.add_run(value)
            _set_east_asia_font(run, "宋体", 8.5, bold=row_index == 0)


def render_docx(document: ContractDocument, output_path: Path) -> Path:
    path = Path(output_path)
    if path.suffix.lower() != ".docx":
        raise ValueError("DOCX 输出路径必须使用 .docx 扩展名")
    path.parent.mkdir(parents=True, exist_ok=True)

    word = WordDocument()
    section = word.sections[0]
    section.page_width = Mm(210)
    section.page_height = Mm(297)
    section.top_margin = Mm(22)
    section.bottom_margin = Mm(20)
    section.left_margin = Mm(22)
    section.right_margin = Mm(22)

    normal = word.styles["Normal"]
    normal.font.name = "宋体"
    normal.font.size = Pt(10.5)
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    header = section.header.paragraphs[0]
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    header_run = header.add_run(f"{document.case_id}　合成验收样本")
    _set_east_asia_font(header_run, "微软雅黑", 8)
    header_run.font.color.rgb = RGBColor(127, 127, 127)
    _add_page_number(section.footer.paragraphs[0])

    marker = word.add_paragraph()
    marker.alignment = WD_ALIGN_PARAGRAPH.CENTER
    marker_run = marker.add_run(document.header_lines[0])
    _set_east_asia_font(marker_run, "微软雅黑", 10, bold=True)
    marker_run.font.color.rgb = RGBColor(192, 0, 0)

    title = word.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_before = Pt(80)
    title.paragraph_format.space_after = Pt(30)
    title_run = title.add_run(document.title)
    _set_east_asia_font(title_run, "微软雅黑", 22, bold=True)
    for line in document.header_lines[1:]:
        paragraph = word.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _set_east_asia_font(paragraph.add_run(line), "宋体", 11)
    notice = word.add_paragraph()
    notice.alignment = WD_ALIGN_PARAGRAPH.CENTER
    notice.paragraph_format.space_before = Pt(80)
    notice_run = notice.add_run("本文件所有主体、金额、编号和签署信息均为合成内容")
    _set_east_asia_font(notice_run, "宋体", 9)
    notice_run.font.color.rgb = RGBColor(127, 127, 127)

    for page_blocks in paginate_document(document):
        word.add_page_break()
        for block in page_blocks:
            heading = _word_paragraph(word, block.heading, size=12, bold=True)
            heading.paragraph_format.keep_with_next = True
            heading.paragraph_format.space_before = Pt(5)
            for paragraph in block.paragraphs:
                _word_paragraph(word, paragraph)
            _word_table(word, block.rows)

    properties = word.core_properties
    properties.title = document.title
    properties.subject = "合成测试合同，仅用于系统验收"
    properties.author = "合同审查系统测试生成器"
    properties.keywords = f"synthetic,{document.case_id}"
    word.save(path)
    return path


def _wrap_text(font: fitz.Font, text: str, width: float, size: float) -> list[str]:
    lines: list[str] = []
    for source_line in text.splitlines() or [""]:
        current = ""
        for character in source_line:
            candidate = current + character
            if current and font.text_length(candidate, fontsize=size) > width:
                lines.append(current)
                current = character
            else:
                current = candidate
        lines.append(current)
    return lines or [""]


def _insert_lines(
    page: fitz.Page,
    lines: list[str],
    *,
    x: float,
    y: float,
    fontname: str,
    size: float,
    color: tuple[float, float, float] = (0, 0, 0),
    line_height: float | None = None,
) -> float:
    step = line_height or size * 1.55
    for line in lines:
        page.insert_text((x, y), line, fontname=fontname, fontsize=size, color=color)
        y += step
    return y


def _draw_pdf_table(
    page: fitz.Page,
    rows: tuple[tuple[str, ...], ...],
    *,
    y: float,
    font: fitz.Font,
    fontname: str,
    size: float,
) -> float:
    if not rows:
        return y
    width = A4_RECT.width - PDF_MARGIN_X * 2
    column_count = max(len(row) for row in rows)
    column_width = width / column_count
    for row_index, values in enumerate(rows):
        wrapped = [
            _wrap_text(font, values[index] if index < len(values) else "", column_width - 8, size)
            for index in range(column_count)
        ]
        row_height = max(20.0, max(len(lines) for lines in wrapped) * size * 1.45 + 8)
        for column_index, lines in enumerate(wrapped):
            x0 = PDF_MARGIN_X + column_index * column_width
            rect = fitz.Rect(x0, y, x0 + column_width, y + row_height)
            if row_index == 0:
                page.draw_rect(rect, color=(0.6, 0.6, 0.6), fill=(0.92, 0.92, 0.92), width=0.5)
            else:
                page.draw_rect(rect, color=(0.72, 0.72, 0.72), width=0.45)
            _insert_lines(
                page,
                lines,
                x=x0 + 4,
                y=y + size + 4,
                fontname=fontname,
                size=size,
                line_height=size * 1.35,
            )
        y += row_height
    return y + 5


def _draw_cover(
    page: fitz.Page,
    document: ContractDocument,
    *,
    font: fitz.Font,
    fontname: str,
) -> None:
    banner = fitz.Rect(PDF_MARGIN_X, 48, A4_RECT.width - PDF_MARGIN_X, 82)
    page.draw_rect(banner, color=(0.72, 0.1, 0.1), fill=(1.0, 0.95, 0.95), width=0.7)
    marker_lines = _wrap_text(font, document.header_lines[0], banner.width - 20, 11)
    _insert_lines(page, marker_lines, x=banner.x0 + 10, y=69, fontname=fontname, size=11, color=(0.65, 0.05, 0.05))
    title_lines = _wrap_text(font, document.title, A4_RECT.width - 140, 22)
    title_height = len(title_lines) * 34
    y = 220 - title_height / 2
    for line in title_lines:
        line_width = font.text_length(line, fontsize=22)
        y = _insert_lines(page, [line], x=(A4_RECT.width - line_width) / 2, y=y, fontname=fontname, size=22, line_height=34)
    y = 310
    for line in document.header_lines[1:]:
        line_width = font.text_length(line, fontsize=11)
        y = _insert_lines(page, [line], x=(A4_RECT.width - line_width) / 2, y=y, fontname=fontname, size=11, line_height=25)
    notice = "所有主体、金额、编号和签署信息均为合成内容，不构成法律文件"
    notice_width = font.text_length(notice, fontsize=9)
    _insert_lines(page, [notice], x=(A4_RECT.width - notice_width) / 2, y=650, fontname=fontname, size=9, color=(0.45, 0.45, 0.45))


def _draw_content_page(
    page: fitz.Page,
    document: ContractDocument,
    blocks: tuple[_RenderBlock, ...],
    *,
    page_number: int,
    font: fitz.Font,
    fontname: str,
) -> None:
    page.insert_text((PDF_MARGIN_X, 28), document.title, fontname=fontname, fontsize=7.5, color=(0.45, 0.45, 0.45))
    header_right = f"{document.case_id}　合成验收样本"
    header_width = font.text_length(header_right, fontsize=7.5)
    page.insert_text((A4_RECT.width - PDF_MARGIN_X - header_width, 28), header_right, fontname=fontname, fontsize=7.5, color=(0.45, 0.45, 0.45))
    y = PDF_TOP
    body_width = A4_RECT.width - PDF_MARGIN_X * 2
    for block in blocks:
        heading_lines = _wrap_text(font, block.heading, body_width, 11.5)
        y = _insert_lines(page, heading_lines, x=PDF_MARGIN_X, y=y, fontname=fontname, size=11.5, line_height=17)
        for paragraph in block.paragraphs:
            lines = _wrap_text(font, paragraph, body_width - 14, 9.2)
            y = _insert_lines(page, lines, x=PDF_MARGIN_X + 14, y=y + 2, fontname=fontname, size=9.2, line_height=14.2)
        y = _draw_pdf_table(page, block.rows, y=y + 2, font=font, fontname=fontname, size=7.6)
        y += 4
    if y > A4_RECT.height - PDF_BOTTOM - 18:
        raise RuntimeError(
            f"{document.case_id} 第 {page_number} 页内容溢出："
            f"实际底部 {y:.1f}，可用底部 {A4_RECT.height - PDF_BOTTOM - 18:.1f}"
        )
    footer = f"第 {page_number} 页 / 共 {document.target_pages} 页"
    footer_width = font.text_length(footer, fontsize=7.5)
    page.insert_text(((A4_RECT.width - footer_width) / 2, A4_RECT.height - 23), footer, fontname=fontname, fontsize=7.5, color=(0.45, 0.45, 0.45))


def _text_pdf_bytes(document: ContractDocument) -> bytes:
    font_path = resolve_cjk_font()
    font = fitz.Font(fontfile=str(font_path))
    fontname = "SyntheticCJK"
    pdf = fitz.open()
    try:
        cover = pdf.new_page(width=A4_RECT.width, height=A4_RECT.height)
        cover.insert_font(fontname=fontname, fontfile=str(font_path))
        _draw_cover(cover, document, font=font, fontname=fontname)
        for page_number, blocks in enumerate(paginate_document(document), start=2):
            page = pdf.new_page(width=A4_RECT.width, height=A4_RECT.height)
            page.insert_font(fontname=fontname, fontfile=str(font_path))
            _draw_content_page(page, document, blocks, page_number=page_number, font=font, fontname=fontname)
        pdf.set_metadata({
            "title": document.title,
            "author": "合同审查系统测试生成器",
            "subject": "合成测试合同，仅用于系统验收",
            "keywords": f"synthetic,{document.case_id}",
        })
        pdf.subset_fonts()
        return pdf.tobytes(garbage=4, deflate=True)
    finally:
        pdf.close()


def render_text_pdf(document: ContractDocument, output_path: Path) -> Path:
    path = Path(output_path)
    if path.suffix.lower() != ".pdf":
        raise ValueError("PDF 输出路径必须使用 .pdf 扩展名")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_text_pdf_bytes(document))
    return path


def _scan_page_image(
    page: fitz.Page,
    profile: ScanProfile,
    page_index: int,
) -> bytes:
    pixmap = page.get_pixmap(dpi=profile.dpi, alpha=False)
    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    angle = profile.rotation_degrees if page_index % 2 == 0 else -profile.rotation_degrees
    image = image.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False, fillcolor=(246, 246, 243))
    image = ImageEnhance.Brightness(image).enhance(profile.brightness)
    image = ImageEnhance.Contrast(image).enhance(profile.contrast)
    draw = ImageDraw.Draw(image)
    for offset in range(profile.shadow_width):
        shade = 205 + int(45 * offset / max(profile.shadow_width, 1))
        draw.line((offset, 0, offset, image.height), fill=(shade, shade, shade))
    stream = BytesIO()
    image.save(stream, format="JPEG", quality=profile.jpeg_quality, optimize=True)
    return stream.getvalue()


def _render_image_pdf(
    document: ContractDocument,
    *,
    profile: ScanProfile,
    preserve_text_every: int | None,
) -> bytes:
    source = fitz.open(stream=_text_pdf_bytes(document), filetype="pdf")
    output = fitz.open()
    try:
        for index, source_page in enumerate(source):
            target = output.new_page(width=source_page.rect.width, height=source_page.rect.height)
            preserve = preserve_text_every is not None and index % preserve_text_every == 0
            if preserve:
                target.show_pdf_page(target.rect, source, index)
            else:
                image = _scan_page_image(source_page, profile, index)
                target.insert_image(target.rect, stream=image)
        output.set_metadata({
            "title": document.title,
            "author": "合同审查系统测试生成器",
            "subject": "合成扫描测试合同，仅用于系统验收",
            "keywords": f"synthetic,scan,{document.case_id}",
        })
        return output.tobytes(garbage=4, deflate=True)
    finally:
        output.close()
        source.close()


def render_scanned_pdf(
    document: ContractDocument,
    output_path: Path,
    *,
    profile: ScanProfile,
) -> Path:
    path = Path(output_path)
    if path.suffix.lower() != ".pdf":
        raise ValueError("扫描 PDF 输出路径必须使用 .pdf 扩展名")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_render_image_pdf(document, profile=profile, preserve_text_every=None))
    return path


def render_mixed_pdf(
    document: ContractDocument,
    output_path: Path,
    *,
    profile: ScanProfile,
) -> Path:
    path = Path(output_path)
    if path.suffix.lower() != ".pdf":
        raise ValueError("混合 PDF 输出路径必须使用 .pdf 扩展名")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_render_image_pdf(document, profile=profile, preserve_text_every=3))
    return path
