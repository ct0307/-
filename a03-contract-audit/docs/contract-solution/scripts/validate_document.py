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
CURRENT_EVENT = "2026“数字马力杯”第十三届浙江省大学生服务外包创新应用大赛"
OUTDATED_EVENT = "浙江省职业技能大赛 · 外包赛道"
CHAPTER = re.compile(r"^第[一二三四五六七八九十]+章\s")
SOURCE_ROOT = Path(__file__).resolve().parents[1]
PROFILES = {
    "legacy": {
        "chapters": 17,
        "chars": (25000, 35000),
        "tables": (10, 15),
        "images": (20, 30),
        "pages": (40, 50),
        "margins": {"top": "1080", "bottom": "1080", "left": "1080", "right": "1080"},
        "header": "560",
        "footer": "560",
        "sources": tuple(range(1, 14)),
        "banned": BANNED,
        "min_alt": 20,
        "min_bookmarks": 40,
        "include_table_text": False,
        "required_facts": (),
        "forbidden_facts": (),
    },
    "redesign": {
        "chapters": 7,
        "chars": (27000, 33000),
        "tables": (8, 10),
        "images": (22, 28),
        "pages": (42, 46),
        "margins": {"top": "1134", "bottom": "1134", "left": "1134", "right": "1134"},
        "header": "851",
        "footer": "992",
        "sources": tuple(range(1, 7)),
        "banned": None,
        "min_alt": 22,
        "min_bookmarks": 30,
        "include_table_text": True,
        "required_facts": (CURRENT_EVENT,),
        "forbidden_facts": (OUTDATED_EVENT,),
    },
}
EXPECTED_IMAGES = {
    *(f"{index:02d}-{name}.png" for index, name in enumerate([
        "problem-solution", "user-collaboration", "functional-architecture",
        "contract-review-flow", "technical-architecture", "private-deployment",
        "agent-sequence", "rag-evidence-flow", "parsing-data-flow", "core-er",
        "security-layers", "implementation-roadmap", "testing-loop", "product-roadmap",
    ], start=1)),
    "01-login.png", "02-dashboard.png", "03-audit.png", "04-risk-review.png",
    "05-collaboration.png", "06-rectify.png", "07-reports.png", "08-knowledge.png",
    "09-admin.png", "10-reports-normal.png",
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


def require_style(styles_root: ET.Element, style_id: str, font: str, size: str) -> None:
    style = styles_root.find(f".//w:style[@w:styleId='{style_id}']", NS)
    if style is None:
        fail(f"缺少样式：{style_id}")
    fonts = style.find("w:rPr/w:rFonts", NS)
    size_node = style.find("w:rPr/w:sz", NS)
    if fonts is None or fonts.get(W + "eastAsia") != font:
        fail(f"{style_id} 东亚字体应为 {font}")
    if size_node is None or size_node.get(W + "val") != size:
        fail(f"{style_id} 字号应为 {int(size) / 2:g}pt")


def validate_redesign_layout(archive: zipfile.ZipFile, root: ET.Element) -> None:
    styles_xml = xml_text(archive, "word/styles.xml")
    styles_root = ET.fromstring(styles_xml)
    require_style(styles_root, "Normal", "楷体", "24")
    require_style(styles_root, "Heading1", "黑体", "30")
    require_style(styles_root, "Heading2", "宋体", "28")
    require_style(styles_root, "Heading3", "宋体", "24")
    require_style(styles_root, "Caption", "楷体", "21")

    document_xml = ET.tostring(root, encoding="unicode")
    forbidden_colors = ("245B78", "4C7A92", "C48A2C", "E8F0F4", "F4F6F9")
    if any(color in styles_xml or color in document_xml for color in forbidden_colors):
        fail("redesign 仍包含旧版主题色")

    colored_fills = [
        node.get(W + "fill")
        for node in root.findall(".//w:tbl//w:shd", NS)
        if node.get(W + "fill") not in (None, "auto", "FFFFFF")
    ]
    if colored_fills:
        fail(f"表格仍包含彩色底纹：{colored_fills[0]}")


def validate_docx(path: Path, profile: str) -> dict[str, int]:
    if not path.exists() or path.stat().st_size == 0:
        fail(f"DOCX 不存在或为空：{path}")

    doc = Document(path)
    paragraph_text = "\n".join(p.text for p in doc.paragraphs)
    chapter_titles = [p.text.strip() for p in doc.paragraphs if CHAPTER.match(p.text.strip())]
    config = PROFILES[profile]
    if len(chapter_titles) != config["chapters"]:
        fail(f"一级章节应为 {config['chapters']} 个，实际 {len(chapter_titles)} 个")
    if len(set(chapter_titles)) != config["chapters"]:
        fail("一级章节标题存在重复")
    for fact in config["required_facts"]:
        if fact not in paragraph_text:
            fail(f"缺少必要事实：{fact}")
    for fact in config["forbidden_facts"]:
        if fact in paragraph_text:
            fail(f"发现过期事实：{fact}")

    counted_text = paragraph_text
    if config["include_table_text"]:
        table_text = "\n".join(
            cell.text for table in doc.tables for row in table.rows for cell in row.cells
        )
        counted_text = f"{counted_text}\n{table_text}"
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", counted_text))
    char_min, char_max = config["chars"]
    if not char_min <= chinese_chars <= char_max:
        fail(f"正文中文字符应为 {char_min}～{char_max}，实际 {chinese_chars}")
    banned = config["banned"]
    if banned is not None and banned.search(paragraph_text):
        fail(f"发现禁用表述：{banned.search(paragraph_text).group(0)}")
    missing_sources = [
        f"[S{index:02d}]" for index in config["sources"]
        if f"[S{index:02d}]" not in paragraph_text
    ]
    if missing_sources:
        fail(f"参考文献不完整：{', '.join(missing_sources)}")

    table_count = len(doc.tables)
    table_min, table_max = config["tables"]
    if not table_min <= table_count <= table_max:
        fail(f"表格数应为 {table_min}～{table_max}，实际 {table_count}")

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
        image_min, image_max = config["images"]
        if not image_min <= len(media) <= image_max:
            fail(f"有效图片数应为 {image_min}～{image_max}，实际 {len(media)}")
        if "TargetMode=\"External\"" not in rels_xml:
            fail("参考文献 URL 未生成外部超链接")

        section = root.find(".//w:sectPr", NS)
        page_size = section.find("w:pgSz", NS) if section is not None else None
        page_margin = section.find("w:pgMar", NS) if section is not None else None
        if page_size is None or page_size.get(W + "w") != "11906" or page_size.get(W + "h") != "16838":
            fail("页面尺寸不是 A4")
        expected_margins = config["margins"]
        if page_margin is None or any(page_margin.get(W + key) != value for key, value in expected_margins.items()):
            fail("页边距与 profile 不一致")
        if page_margin.get(W + "header") != config["header"] or page_margin.get(W + "footer") != config["footer"]:
            fail("页眉页脚距离与 profile 不一致")
        if profile == "redesign":
            validate_redesign_layout(archive, root)

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
        if len([value for value in alt_descriptions if value.strip()]) < config["min_alt"]:
            fail("图片替代文字不足")
        if len(root.findall(".//w:bookmarkStart", NS)) < config["min_bookmarks"]:
            fail("章节与图题书签不足")

    actual_images = {
        item.name for folder in (SOURCE_ROOT / "assets" / "diagrams", SOURCE_ROOT / "assets" / "screenshots")
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


def validate_pdf(path: Path, profile: str) -> int:
    if not path.exists() or path.stat().st_size == 0:
        fail(f"PDF 不存在或为空：{path}")
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = len(reader.pages)
    page_min, page_max = PROFILES[profile]["pages"]
    if not page_min <= pages <= page_max:
        fail(f"PDF 页数应为 {page_min}～{page_max}，实际 {pages}")
    if profile == "redesign":
        chapter_pages: list[int] = []
        for page_number, page in enumerate(reader.pages[2:], start=3):
            lines = [line.strip() for line in (page.extract_text() or "").splitlines()]
            for line_number, line in enumerate(lines):
                if not CHAPTER.match(line):
                    continue
                leading_lines = [
                    value
                    for value in lines[:line_number]
                    if value
                    and not (value.startswith("契鉴") and "项目详细方案" in value)
                    and not (value.startswith("V2.0") and "第" in value and "页" in value)
                ]
                if leading_lines:
                    fail(f"{line} 未独立起页，位于 PDF 第 {page_number} 页正文中部")
                chapter_pages.append(page_number)
        if len(chapter_pages) != PROFILES[profile]["chapters"]:
            fail(f"PDF 中应识别 {PROFILES[profile]['chapters']} 个独立起页章节，实际 {len(chapter_pages)}")
    return pages


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=PROFILES, default="legacy")
    parser.add_argument("docx", type=Path)
    parser.add_argument("pdf", nargs="?", type=Path)
    args = parser.parse_args()

    try:
        result = validate_docx(args.docx.resolve(), args.profile)
        if args.pdf:
            result["pages"] = validate_pdf(args.pdf.resolve(), args.profile)
    except (AssertionError, zipfile.BadZipFile, KeyError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    print("PASS " + " ".join(f"{key}={value}" for key, value in result.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
