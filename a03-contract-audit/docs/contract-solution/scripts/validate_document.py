"""验证《契鉴》项目详细方案 DOCX/PDF 的结构与交付门槛。"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from docx import Document


BANNED = re.compile(r"当前已|已经完成|截至目前|后续完善|完成度|现有项目|本项目目前")
CHAPTER = re.compile(r"^第[一二三四五六七八九十]+章\s")
SOURCE = re.compile(r"\[S(?:0[1-9]|1[0-3])\]")
EXPECTED_IMAGES = {
    *(f"{index:02d}-{name}.png" for index, name in enumerate([
        "problem-solution", "user-collaboration", "functional-architecture",
        "contract-review-flow", "technical-architecture", "private-deployment",
        "agent-sequence", "rag-evidence-flow", "parsing-data-flow", "core-er",
        "security-layers", "implementation-roadmap", "testing-loop", "product-roadmap",
    ], start=1)),
    "01-login.png", "02-dashboard.png", "03-audit.png", "04-risk-review.png",
    "05-collaboration.png", "06-rectify.png", "07-reports.png", "08-knowledge.png",
    "09-admin.png",
}
NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
}
W = f"{{{NS['w']}}}"


def fail(message: str) -> None:
    raise AssertionError(message)


def xml_text(archive: zipfile.ZipFile, name: str) -> str:
    return archive.read(name).decode("utf-8")


def validate_docx(path: Path) -> dict[str, int]:
    if not path.exists() or path.stat().st_size == 0:
        fail(f"DOCX 不存在或为空：{path}")

    doc = Document(path)
    paragraph_text = "\n".join(p.text for p in doc.paragraphs)
    chapter_titles = [p.text.strip() for p in doc.paragraphs if CHAPTER.match(p.text.strip())]
    if len(chapter_titles) != 17:
        fail(f"一级章节应为 17 个，实际 {len(chapter_titles)} 个")
    if len(set(chapter_titles)) != 17:
        fail("一级章节标题存在重复")

    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", paragraph_text))
    if not 25000 <= chinese_chars <= 35000:
        fail(f"正文中文字符应为 25000～35000，实际 {chinese_chars}")
    if BANNED.search(paragraph_text):
        fail(f"发现禁用表述：{BANNED.search(paragraph_text).group(0)}")
    if not all(f"[S{index:02d}]" in paragraph_text for index in range(1, 14)):
        fail("参考文献 [S01]～[S13] 不完整")

    table_count = len(doc.tables)
    if not 10 <= table_count <= 15:
        fail(f"表格数应为 10～15，实际 {table_count}")

    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        document_xml = xml_text(archive, "word/document.xml")
        rels_xml = xml_text(archive, "word/_rels/document.xml.rels")
        root = ET.fromstring(document_xml)
        if "TOC \\o &quot;1-3&quot;" not in document_xml and "TOC \\h" not in document_xml:
            fail("未发现目录 TOC 域")
        headers = [name for name in names if re.fullmatch(r"word/header\d+\.xml", name)]
        footers = [name for name in names if re.fullmatch(r"word/footer\d+\.xml", name)]
        if not headers or not footers:
            fail("缺少页眉或页脚部件")
        if "PAGE" not in "".join(xml_text(archive, name) for name in footers):
            fail("页脚缺少页码域")
        media = [name for name in names if name.startswith("word/media/") and not name.endswith("/")]
        if not 20 <= len(media) <= 30:
            fail(f"有效图片数应为 20～30，实际 {len(media)}")
        if "TargetMode=\"External\"" not in rels_xml:
            fail("参考文献 URL 未生成外部超链接")

        section = root.find(".//w:sectPr", NS)
        page_size = section.find("w:pgSz", NS) if section is not None else None
        page_margin = section.find("w:pgMar", NS) if section is not None else None
        if page_size is None or page_size.get(W + "w") != "11906" or page_size.get(W + "h") != "16838":
            fail("页面尺寸不是 A4")
        expected_margins = {"top": "1440", "bottom": "1440", "left": "1474", "right": "1474"}
        if page_margin is None or any(page_margin.get(W + key) != value for key, value in expected_margins.items()):
            fail("页边距与设计令牌不一致")

        xml_tables = root.findall(".//w:tbl", NS)
        if len(xml_tables) != table_count:
            fail("python-docx 与 OOXML 表格计数不一致")
        for index, table in enumerate(xml_tables, start=1):
            table_width = table.find("w:tblPr/w:tblW", NS)
            table_indent = table.find("w:tblPr/w:tblInd", NS)
            grid_widths = [int(item.get(W + "w")) for item in table.findall("w:tblGrid/w:gridCol", NS)]
            if table_width is None or int(table_width.get(W + "w", "0")) != sum(grid_widths):
                fail(f"第 {index} 张表 tblW 与 tblGrid 不一致")
            if table_indent is None or table_indent.get(W + "w") != "120":
                fail(f"第 {index} 张表 tblInd 不是 120 DXA")
            for row in table.findall("w:tr", NS):
                cell_widths = [int(cell.get(W + "w")) for cell in row.findall("w:tc/w:tcPr/w:tcW", NS)]
                if cell_widths != grid_widths:
                    fail(f"第 {index} 张表 tcW 与 tblGrid 不一致")

        alt_descriptions = [node.get("descr", "") for node in root.findall(".//wp:docPr", NS)]
        if len([value for value in alt_descriptions if value.strip()]) < 20:
            fail("图片替代文字不足")
        if len(root.findall(".//w:bookmarkStart", NS)) < 40:
            fail("章节与图题书签不足")

    source_root = path.parent
    actual_images = {
        item.name for folder in (source_root / "assets" / "diagrams", source_root / "assets" / "screenshots")
        for item in folder.glob("*.png")
    }
    missing = EXPECTED_IMAGES - actual_images
    if missing:
        fail(f"源图片缺失：{', '.join(sorted(missing))}")

    return {
        "chapters": len(chapter_titles),
        "chinese_chars": chinese_chars,
        "tables": table_count,
        "images": len(media),
    }


def validate_pdf(path: Path) -> int:
    if not path.exists() or path.stat().st_size == 0:
        fail(f"PDF 不存在或为空：{path}")
    from pypdf import PdfReader

    pages = len(PdfReader(str(path)).pages)
    if not 40 <= pages <= 50:
        fail(f"PDF 页数应为 40～50，实际 {pages}")
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
    except (AssertionError, zipfile.BadZipFile, KeyError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    print("PASS " + " ".join(f"{key}={value}" for key, value in result.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
