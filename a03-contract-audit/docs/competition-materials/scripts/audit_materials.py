"""审计重构版参赛材料的结构、占位符、宣传性表述和跨文档重复。"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from dataclasses import dataclass
from pathlib import Path


PROMOTIONAL_PHRASES = (
    "全面赋能",
    "颠覆性创新",
    "革命性突破",
    "行业绝对领先",
    "完全替代人工",
)
FREQUENCY_TERMS = ("闭环", "能力", "目标", "验收")
LEVEL_FOUR_HEADING = re.compile(r"(?m)^#{4,}\s+.+$")
PLACEHOLDER = re.compile(
    r"此处插入|待填写|待补充|"
    r"(?<![A-Za-z])TODO(?![A-Za-z])|"
    r"(?<![A-Za-z])TBD(?![A-Za-z])|"
    r"(?<![A-Za-z])PLACEHOLDER(?![A-Za-z])|"
    r"(?<![A-Za-z])X{3,}(?![A-Za-z])",
    re.IGNORECASE,
)
CHAPTER_HEADING = re.compile(r"(?m)^#\s+第[一二三四五六七八九十]+章\s+.+$")
OVERVIEW_PAGE = re.compile(r"(?m)^# PAGE:\s+.+$")


@dataclass(frozen=True)
class SimilarityFinding:
    detail_index: int
    overview_index: int
    ratio: float
    detail_excerpt: str
    overview_excerpt: str


def find_level_four_headings(text: str) -> list[str]:
    return [match.group(0).strip() for match in LEVEL_FOUR_HEADING.finditer(text)]


def find_placeholders(text: str) -> list[str]:
    return [match.group(0) for match in PLACEHOLDER.finditer(text)]


def find_promotional_phrases(text: str) -> list[str]:
    pattern = re.compile("|".join(re.escape(phrase) for phrase in PROMOTIONAL_PHRASES))
    return [match.group(0) for match in pattern.finditer(text)]


def material_paragraphs(text: str, minimum_length: int) -> list[str]:
    paragraphs: list[str] = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        if all(line.startswith(("#", "!", "|")) for line in lines):
            continue
        paragraph = " ".join(lines)
        paragraph = re.sub(r"^>\s*", "", paragraph)
        paragraph = re.sub(r"\*\*(.+?)\*\*", r"\1", paragraph)
        compact = re.sub(r"\s+", "", paragraph)
        if len(compact) >= minimum_length:
            paragraphs.append(compact)
    return paragraphs


def similarity_pairs(
    detail_text: str,
    overview_text: str,
    minimum_length: int,
) -> list[SimilarityFinding]:
    detail_paragraphs = material_paragraphs(detail_text, minimum_length)
    overview_paragraphs = material_paragraphs(overview_text, minimum_length)
    findings: list[SimilarityFinding] = []
    for detail_index, detail in enumerate(detail_paragraphs, start=1):
        for overview_index, overview in enumerate(overview_paragraphs, start=1):
            ratio = difflib.SequenceMatcher(None, detail, overview, autojunk=False).ratio()
            findings.append(
                SimilarityFinding(
                    detail_index=detail_index,
                    overview_index=overview_index,
                    ratio=ratio,
                    detail_excerpt=detail[:48],
                    overview_excerpt=overview[:48],
                )
            )
    return findings


def audit_similarity(
    detail_text: str,
    overview_text: str,
    minimum_length: int = 80,
    threshold: float = 0.80,
) -> list[SimilarityFinding]:
    return [
        finding
        for finding in similarity_pairs(detail_text, overview_text, minimum_length)
        if finding.ratio >= threshold
    ]


def read_detail_sources(detail_dir: Path) -> tuple[list[Path], str]:
    paths = sorted(detail_dir.glob("*.md"))
    return paths, "\n\n".join(path.read_text(encoding="utf-8") for path in paths)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--detail-dir", required=True, type=Path)
    parser.add_argument("--overview", required=True, type=Path)
    parser.add_argument("--minimum-length", type=int, default=80)
    parser.add_argument("--threshold", type=float, default=0.80)
    args = parser.parse_args(argv)

    detail_paths, detail_text = read_detail_sources(args.detail_dir.resolve())
    overview_path = args.overview.resolve()
    overview_text = overview_path.read_text(encoding="utf-8")
    sources = [(path, path.read_text(encoding="utf-8")) for path in detail_paths]
    sources.append((overview_path, overview_text))

    violations: list[str] = []
    placeholders = 0
    promotional_phrases = 0
    for path, text in sources:
        for heading in find_level_four_headings(text):
            violations.append(f"{path}: 四级或更深标题：{heading}")
        source_placeholders = find_placeholders(text)
        source_promotional = find_promotional_phrases(text)
        placeholders += len(source_placeholders)
        promotional_phrases += len(source_promotional)
        for placeholder in source_placeholders:
            violations.append(f"{path}: 占位标记：{placeholder}")
        for phrase in source_promotional:
            violations.append(f"{path}: 宣传性表述：{phrase}")

    detail_chapters = len(CHAPTER_HEADING.findall(detail_text))
    overview_pages = len(OVERVIEW_PAGE.findall(overview_text))
    if detail_chapters != 7:
        violations.append(f"{args.detail_dir}: 一级章节应为 7 个，实际 {detail_chapters}")
    if overview_pages != 9:
        violations.append(f"{overview_path}: 页面应为 9 个，实际 {overview_pages}")

    pairs = similarity_pairs(detail_text, overview_text, args.minimum_length)
    repeated = [finding for finding in pairs if finding.ratio >= args.threshold]
    for finding in repeated:
        violations.append(
            f"{args.detail_dir} <-> {overview_path}: 长段相似度 {finding.ratio:.3f}；"
            f"详细方案段落“{finding.detail_excerpt}”；概要段落“{finding.overview_excerpt}”"
        )
    max_similarity = max((finding.ratio for finding in pairs), default=0.0)

    frequencies = {
        term: detail_text.count(term) + overview_text.count(term)
        for term in FREQUENCY_TERMS
    }
    print("INFO " + " ".join(f"{term}={count}" for term, count in frequencies.items()))
    if violations:
        for violation in violations:
            print(f"FAIL {violation}", file=sys.stderr)
        return 1

    print(
        "PASS "
        f"detail_chapters={detail_chapters} "
        f"overview_pages={overview_pages} "
        f"max_similarity={max_similarity:.3f} "
        f"placeholders={placeholders} "
        f"promotional_phrases={promotional_phrases}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
