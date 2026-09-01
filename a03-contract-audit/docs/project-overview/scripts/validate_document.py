"""验证《契鉴》项目概要介绍 DOCX/PDF 的结构、事实与交付质量。"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from docx import Document


NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
}
W = f"{{{NS['w']}}}"
PAGE_TITLES = [
    "前言",
    "项目创意",
    "系统总体方案",
    "功能简介",
    "核心业务流程",
    "技术架构与开发环境",
    "应用对象与典型场景",
    "项目优势与安全体系",
    "验证情况与责任边界",
    "结语与发展方向",
    "系统关键界面展示",
]
REQUIRED_FACTS = [
    "2026“数字马力杯”第十三届浙江省大学生服务外包创新应用大赛",
    "契鉴",
    "双 Agent",
    "RAG",
    "13 张数据库表",
    "40 条 /api/ 路由",
    "125 passed",
    "11 passed",
    "待实测",
    "辅助审查意见",
]
BANNED = re.compile(
    r"浙江省职业技能大赛\s*[·|｜]?\s*外包赛道|"
    r"OCR\s*准确率已达|已有客户|客户数量|已实现收入|营业收入|市场份额|"
    r"100%准确|完全替代(?:律师|法务|财务)"
)


def fail(message: str) -> None:
    raise AssertionError(message)


def xml_text(archive: zipfile.ZipFile, name: str) -> str:
    return archive.read(name).decode("utf-8")


def validate_table_geometry(root: ET.Element) -> int:
    tables = root.findall(".//w:tbl", NS)
    for index, table in enumerate(tables, start=1):
        table_width = table.find("w:tblPr/w:tblW", NS)
        grid_widths = [int(item.get(W + "w")) for item in table.findall("w:tblGrid/w:gridCol", NS)]
        if not grid_widths:
            fail(f"第 {index} 张表缺少 tblGrid")
        if table_width is None or int(table_width.get(W + "w", "0")) != sum(grid_widths):
            fail(f"第 {index} 张表 tblW 与 tblGrid 不一致")
        for row in table.findall("w:tr", NS):
            cell_widths = [int(cell.get(W + "w")) for cell in row.findall("w:tc/w:tcPr/w:tcW", NS)]
            if cell_widths != grid_widths:
                fail(f"第 {index} 张表 tcW 与 tblGrid 不一致")
    return len(tables)


def validate_source_images(docx_path: Path) -> int:
    source_path = docx_path.parent / "content" / "overview.md"
    if not source_path.exists():
        fail(f"缺少内容源：{source_path}")
    text = source_path.read_text(encoding="utf-8")
    image_refs = re.findall(r"!\[[^]]+\]\(([^)]+)\)", text)
    if len(image_refs) != 12:
        fail(f"内容源应引用 12 张图片，实际 {len(image_refs)}")
    for image_ref in image_refs:
        image_path = (source_path.parent / image_ref).resolve()
        if not image_path.exists() or image_path.stat().st_size == 0:
            fail(f"源图片不存在或为空：{image_path}")
    return len(image_refs)


def validate_docx(path: Path) -> dict[str, int]:
    if not path.exists() or path.stat().st_size == 0:
        fail(f"DOCX 不存在或为空：{path}")

    doc = Document(path)
    paragraph_text = "\n".join([
        *(paragraph.text for paragraph in doc.paragraphs),
        *(cell.text for table in doc.tables for row in table.rows for cell in row.cells),
    ])
    headings = [
        paragraph.text.strip()
        for paragraph in doc.paragraphs
        if paragraph.style and paragraph.style.name == "Heading 1"
    ]
    if len(headings) != len(PAGE_TITLES):
        fail(f"正文页标题应为 {len(PAGE_TITLES)} 个，实际 {len(headings)}")
    for title in PAGE_TITLES:
        if not any(title in heading for heading in headings):
            fail(f"缺少页面标题：{title}")
    for fact in REQUIRED_FACTS:
        if fact not in paragraph_text:
            fail(f"缺少关键事实或边界：{fact}")
    match = BANNED.search(paragraph_text)
    if match:
        fail(f"发现禁用或不可证实表述：{match.group(0)}")

    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", paragraph_text))
    if not 2500 <= chinese_chars <= 6500:
        fail(f"正文中文字符应为 2500～6500，实际 {chinese_chars}")

    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        document_xml = xml_text(archive, "word/document.xml")
        root = ET.fromstring(document_xml)
        page_breaks = [
            node for node in root.findall(".//w:br", NS)
            if node.get(W + "type") == "page"
        ]
        if len(page_breaks) != 11:
            fail(f"显式分页符应为 11 个，实际 {len(page_breaks)}")

        section = root.find(".//w:sectPr", NS)
        page_size = section.find("w:pgSz", NS) if section is not None else None
        page_margin = section.find("w:pgMar", NS) if section is not None else None
        if page_size is None or page_size.get(W + "w") != "11906" or page_size.get(W + "h") != "16838":
            fail("页面尺寸不是 A4")
        expected_margins = {"top": "1134", "bottom": "1134", "left": "1134", "right": "1134"}
        if page_margin is None or any(page_margin.get(W + key) != value for key, value in expected_margins.items()):
            fail("页边距不是 20 mm")

        headers = [name for name in names if re.fullmatch(r"word/header\d+\.xml", name)]
        footers = [name for name in names if re.fullmatch(r"word/footer\d+\.xml", name)]
        if len(headers) < 2 or len(footers) < 2:
            fail("缺少封面/正文页眉或页脚部件")
        if "PAGE" not in "".join(xml_text(archive, name) for name in footers):
            fail("正文页脚缺少 PAGE 域")

        media = [name for name in names if name.startswith("word/media/") and not name.endswith("/")]
        if len(media) != 12:
            fail(f"嵌入图片应为 12 张，实际 {len(media)}")
        alt_descriptions = [node.get("descr", "") for node in root.findall(".//wp:docPr", NS)]
        if len(alt_descriptions) != 12 or any(not value.strip() for value in alt_descriptions):
            fail("图片替代文字缺失或数量不一致")

        table_count = validate_table_geometry(root)
        if table_count != len(doc.tables):
            fail("python-docx 与 OOXML 表格计数不一致")

    source_images = validate_source_images(path)
    return {
        "pages": 12,
        "headings": len(headings),
        "tables": len(doc.tables),
        "images": source_images,
        "chinese_chars": chinese_chars,
    }


def validate_pdf(path: Path) -> int:
    if not path.exists() or path.stat().st_size == 0:
        fail(f"PDF 不存在或为空：{path}")
    from pypdf import PdfReader

    pages = len(PdfReader(str(path)).pages)
    if pages != 12:
        fail(f"PDF 应为 12 页，实际 {pages}")
    return pages


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("docx", type=Path)
    parser.add_argument("pdf", nargs="?", type=Path)
    args = parser.parse_args()

    try:
        result = validate_docx(args.docx.resolve())
        if args.pdf:
            result["pages"] = validate_pdf(args.pdf.resolve())
    except (AssertionError, zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    print("PASS " + " ".join(f"{key}={value}" for key, value in result.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
