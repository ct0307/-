"""从已下载的官方 DOCX/HTML 机械提取规范化 UTF-8 法源文本。"""
from __future__ import annotations

import argparse
import re
import xml.etree.ElementTree as ET
import zipfile
from html.parser import HTMLParser
from pathlib import Path


_WORD_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def extract_civil_code(docx_path: Path) -> str:
    with zipfile.ZipFile(docx_path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    paragraphs = [
        "".join(node.text or "" for node in paragraph.findall(".//w:t", _WORD_NS)).strip()
        for paragraph in root.findall(".//w:p", _WORD_NS)
    ]
    paragraphs = [paragraph for paragraph in paragraphs if paragraph]
    first_article = next(
        index for index, paragraph in enumerate(paragraphs) if paragraph.startswith("第一条")
    )
    body_start = max(
        index
        for index, paragraph in enumerate(paragraphs[:first_article])
        if re.match(r"^第一编", paragraph)
    )
    return "\n".join(paragraphs[body_start:]) + "\n"


class _ContentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.in_paragraph = False
        self.paragraph_parts: list[str] = []
        self.paragraphs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "div" and attributes.get("id") == "gb_content":
            self.depth = 1
            return
        if self.depth:
            if tag == "div":
                self.depth += 1
            elif tag == "p":
                self.in_paragraph = True
                self.paragraph_parts = []

    def handle_endtag(self, tag: str) -> None:
        if not self.depth:
            return
        if tag == "p" and self.in_paragraph:
            paragraph = "".join(self.paragraph_parts).strip()
            if paragraph:
                self.paragraphs.append(paragraph)
            self.in_paragraph = False
            self.paragraph_parts = []
        elif tag == "div":
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.depth and self.in_paragraph:
            self.paragraph_parts.append(data)


def extract_contract_interpretation(html_path: Path) -> str:
    parser = _ContentParser()
    parser.feed(html_path.read_text(encoding="utf-8"))
    first_article = next(
        index for index, paragraph in enumerate(parser.paragraphs)
        if paragraph.startswith("第一条")
    )
    title_start = max(
        index for index, paragraph in enumerate(parser.paragraphs[:first_article])
        if "最高人民法院" in paragraph
    )
    return "\n".join(parser.paragraphs[title_start:]) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="从官方文件提取法律正文")
    parser.add_argument("--civil-code-docx", required=True, type=Path)
    parser.add_argument("--interpretation-html", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "civil-code.txt").write_text(
        extract_civil_code(args.civil_code_docx), encoding="utf-8", newline="\n"
    )
    (args.output_dir / "contract-interpretation-2023.txt").write_text(
        extract_contract_interpretation(args.interpretation_html),
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
