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
SOURCE_ROOT = Path(__file__).resolve().parents[1]
PROFILES = {
    "legacy": {
        "pages": 12,
        "images": 12,
        "chars": (2500, 6500),
        "margins": {"top": "1134", "bottom": "1134", "left": "1134", "right": "1134"},
        "header": "560",
        "footer": "560",
        "source": SOURCE_ROOT / "content" / "overview.md",
        "page_titles": (
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
        ),
        "required_facts": (
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
        ),
    },
    "redesign": {
        "pages": 9,
        "images": 8,
        "chars": (1600, 2200),
        "margins": {"top": "1134", "bottom": "1134", "left": "1134", "right": "1134"},
        "header": "851",
        "footer": "992",
        "source": SOURCE_ROOT / "content" / "overview-redesign.md",
        "page_titles": (
            "为什么做“契鉴”",
            "“契鉴”是什么",
            "一份合同如何完成审查",
            "风险如何被发现和解释",
            "系统如何协同判断",
            "批量任务与多维报表",
            "谁来使用",
            "当前成果与验证边界",
        ),
        "required_facts": (
            "契鉴",
            "双 Agent",
            "风险原文",
            "人工复核",
            "批量任务",
            "多维报表",
            "待真实环境验证",
            "辅助审查意见",
        ),
    },
}
BANNED = re.compile(
    r"浙江省职业技能大赛\s*[·|｜]?\s*外包赛道|"
    r"OCR\s*准确率已达|已有客户|客户数量|已实现收入|营业收入|市场份额|"
    r"100%准确|完全替代(?:律师|法务|财务)"
)


def fail(message: str) -> None:
    raise AssertionError(message)


def xml_text(archive: zipfile.ZipFile, name: str) -> str:
    return archive.read(name).decode("utf-8")


def style_by_identity(styles_root: ET.Element, style_id: str) -> ET.Element | None:
    style = styles_root.find(f".//w:style[@w:styleId='{style_id}']", NS)
    if style is not None:
        return style
    expected_name = {
        "Normal": "normal",
        "Heading1": "heading 1",
        "Heading2": "heading 2",
        "Caption": "caption",
    }[style_id]
    return next((
        candidate
        for candidate in styles_root.findall(".//w:style", NS)
        if (candidate.find("w:name", NS) is not None)
        and candidate.find("w:name", NS).get(W + "val", "").lower() == expected_name
    ), None)


def effective_style_value(styles_root: ET.Element, style: ET.Element, tag: str, attribute: str) -> str | None:
    visited: set[str] = set()
    current = style
    while current is not None:
        node = current.find(f"w:rPr/w:{tag}", NS)
        if node is not None and node.get(W + attribute):
            return node.get(W + attribute)
        based_on = current.find("w:basedOn", NS)
        based_on_id = based_on.get(W + "val") if based_on is not None else None
        if not based_on_id or based_on_id in visited:
            break
        visited.add(based_on_id)
        current = styles_root.find(f".//w:style[@w:styleId='{based_on_id}']", NS)
    default_node = styles_root.find(f"w:docDefaults/w:rPrDefault/w:rPr/w:{tag}", NS)
    return default_node.get(W + attribute) if default_node is not None else None


def require_style(styles_root: ET.Element, style_id: str, font: str, size: str) -> None:
    style = style_by_identity(styles_root, style_id)
    if style is None:
        fail(f"缺少样式：{style_id}")
    if effective_style_value(styles_root, style, "rFonts", "eastAsia") != font:
        fail(f"{style_id} 东亚字体应为 {font}")
    if effective_style_value(styles_root, style, "sz", "val") != size:
        fail(f"{style_id} 字号应为 {int(size) / 2:g}pt")


def validate_redesign_layout(archive: zipfile.ZipFile, root: ET.Element) -> None:
    styles_xml = xml_text(archive, "word/styles.xml")
    styles_root = ET.fromstring(styles_xml)
    require_style(styles_root, "Normal", "楷体", "24")
    require_style(styles_root, "Heading1", "黑体", "30")
    require_style(styles_root, "Heading2", "宋体", "28")
    require_style(styles_root, "Caption", "楷体", "21")

    document_xml = ET.tostring(root, encoding="unicode")
    forbidden_colors = ("28364A", "A33A32", "9A7628", "F4EFDF", "E8EDF2", "F7F8F9")
    if any(color in styles_xml or color in document_xml for color in forbidden_colors):
        fail("redesign 仍包含旧版主题色")

    colored_fills = [
        node.get(W + "fill")
        for node in root.findall(".//w:tbl//w:shd", NS)
        if node.get(W + "fill") not in (None, "auto", "FFFFFF")
    ]
    if colored_fills:
        fail(f"表格仍包含彩色底纹：{colored_fills[0]}")

    image_paragraphs = [
        paragraph
        for paragraph in root.findall(".//w:p", NS)
        if paragraph.find(".//w:drawing", NS) is not None
    ]
    if any(
        (spacing := paragraph.find("w:pPr/w:spacing", NS)) is None
        or spacing.get(W + "lineRule") != "auto"
        for paragraph in image_paragraphs
    ):
        fail("图片段落必须显式使用自动行距，避免继承正文固定行距后被裁切")


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


def validate_source_images(profile: str) -> int:
    config = PROFILES[profile]
    source_path = config["source"]
    if not source_path.exists():
        fail(f"缺少内容源：{source_path}")
    text = source_path.read_text(encoding="utf-8")
    image_refs = re.findall(r"!\[[^]]+\]\(([^)]+)\)", text)
    if len(image_refs) != config["images"]:
        fail(f"内容源应引用 {config['images']} 张图片，实际 {len(image_refs)}")
    for image_ref in image_refs:
        image_path = (source_path.parent / image_ref).resolve()
        if not image_path.exists() or image_path.stat().st_size == 0:
            fail(f"源图片不存在或为空：{image_path}")
    return len(image_refs)


def validate_docx(path: Path, profile: str) -> dict[str, int]:
    if not path.exists() or path.stat().st_size == 0:
        fail(f"DOCX 不存在或为空：{path}")

    doc = Document(path)
    paragraph_text = "\n".join([
        *(paragraph.text for paragraph in doc.paragraphs),
        *(cell.text for table in doc.tables for row in table.rows for cell in row.cells),
    ])
    config = PROFILES[profile]
    headings = [
        paragraph.text.strip()
        for paragraph in doc.paragraphs
        if paragraph.style and paragraph.style.name == "Heading 1"
    ]
    if len(headings) != len(config["page_titles"]):
        fail(f"正文页标题应为 {len(config['page_titles'])} 个，实际 {len(headings)}")
    if profile == "redesign" and any(re.match(r"^\d{2}\s+", heading) for heading in headings):
        fail("页面标题仍包含两位补零编号")
    for title in config["page_titles"]:
        if not any(title in heading for heading in headings):
            fail(f"缺少页面标题：{title}")
    for fact in config["required_facts"]:
        if fact not in paragraph_text:
            fail(f"缺少关键事实或边界：{fact}")
    match = BANNED.search(paragraph_text)
    if match:
        fail(f"发现禁用或不可证实表述：{match.group(0)}")

    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", paragraph_text))
    char_min, char_max = config["chars"]
    if not char_min <= chinese_chars <= char_max:
        fail(f"正文中文字符应为 {char_min}～{char_max}，实际 {chinese_chars}")

    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        document_xml = xml_text(archive, "word/document.xml")
        root = ET.fromstring(document_xml)
        page_breaks = [
            node for node in root.findall(".//w:br", NS)
            if node.get(W + "type") == "page"
        ]
        expected_breaks = config["pages"] - 1
        if len(page_breaks) != expected_breaks:
            fail(f"显式分页符应为 {expected_breaks} 个，实际 {len(page_breaks)}")

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

        headers = [name for name in names if re.fullmatch(r"word/header\d+\.xml", name)]
        footers = [name for name in names if re.fullmatch(r"word/footer\d+\.xml", name)]
        if len(headers) < 2 or len(footers) < 2:
            fail("缺少封面/正文页眉或页脚部件")
        if "PAGE" not in "".join(xml_text(archive, name) for name in footers):
            fail("正文页脚缺少 PAGE 域")

        media = [name for name in names if name.startswith("word/media/") and not name.endswith("/")]
        if len(media) != config["images"]:
            fail(f"嵌入图片应为 {config['images']} 张，实际 {len(media)}")
        alt_descriptions = [node.get("descr", "") for node in root.findall(".//wp:docPr", NS)]
        if len(alt_descriptions) != config["images"] or any(not value.strip() for value in alt_descriptions):
            fail("图片替代文字缺失或数量不一致")

        table_count = validate_table_geometry(root)
        if table_count != len(doc.tables):
            fail("python-docx 与 OOXML 表格计数不一致")

    source_images = validate_source_images(profile)
    return {
        "pages": config["pages"],
        "headings": len(headings),
        "tables": len(doc.tables),
        "images": source_images,
        "chinese_chars": chinese_chars,
    }


def validate_pdf(path: Path, profile: str) -> int:
    if not path.exists() or path.stat().st_size == 0:
        fail(f"PDF 不存在或为空：{path}")
    from pypdf import PdfReader

    pages = len(PdfReader(str(path)).pages)
    expected_pages = PROFILES[profile]["pages"]
    if pages != expected_pages:
        fail(f"PDF 应为 {expected_pages} 页，实际 {pages}")
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
    except (AssertionError, zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    print("PASS " + " ".join(f"{key}={value}" for key, value in result.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
