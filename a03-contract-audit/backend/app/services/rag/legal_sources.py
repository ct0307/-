"""权威法源清单校验与法条解析。"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlparse


class LegalSourceError(ValueError):
    """法源文件或清单不符合受控导入要求。"""


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    title: str
    issuing_authority: str
    official_url: str
    file: str
    file_sha256: str
    included_ranges: tuple[tuple[int, int], ...]
    expected_article_count: int
    publication_date: date
    effective_date: date
    version_status: str
    retrieved_at: date


@dataclass(frozen=True)
class ParsedArticle:
    source_id: str
    article_number: str
    article_sort: int
    chapter_title: str
    content: str
    content_hash: str


@dataclass(frozen=True)
class LegalChunk:
    article_key: tuple[str, str]
    article_number: str
    chunk_index: int
    chunk_count: int
    display_content: str
    retrieval_text: str
    chunk_schema_version: str = "legal-v1"


_OFFICIAL_HOSTS = {
    "flk.npc.gov.cn",
    "npc.gov.cn",
    "www.npc.gov.cn",
    "court.gov.cn",
    "www.court.gov.cn",
    "gongbao.court.gov.cn",
}
_SOURCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ARTICLE_RE = re.compile(
    r"^[\t \u3000]*第(?P<base>[一二三四五六七八九十百千万零〇两\d]+)条"
    r"(?:之(?P<suffix>[一二三四五六七八九十百千万零〇两\d]+))?"
    r"[\t \u3000]*(?P<body>.*)$"
)
_HEADING_RE = re.compile(
    r"^[\t \u3000]*第[一二三四五六七八九十百千万零〇两\d]+"
    r"(?:分编|编|章|节|部分)[^。；]*$"
)
_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3,
           "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[。；;！？!?])")


def chinese_number_to_int(value: str) -> int:
    value = value.strip()
    if value.isdigit():
        return int(value)
    if not value or any(char not in _DIGITS and char not in _UNITS for char in value):
        raise LegalSourceError(f"无法识别条号数字：{value}")
    total = 0
    current = 0
    for char in value:
        if char in _DIGITS:
            current = _DIGITS[char]
            continue
        unit = _UNITS[char]
        if unit == 10000:
            total = (total + current) * unit
        else:
            total += (current or 1) * unit
        current = 0
    return total + current


def int_to_chinese_number(value: int) -> str:
    if value <= 0 or value >= 10000:
        raise LegalSourceError(f"条号超出支持范围：{value}")
    digits = "零一二三四五六七八九"
    units = ("", "十", "百", "千")
    chars: list[str] = []
    zero_pending = False
    for position in range(3, -1, -1):
        divisor = 10 ** position
        digit = value // divisor % 10
        if digit:
            if zero_pending and chars:
                chars.append("零")
            if not (digit == 1 and position == 1 and not chars):
                chars.append(digits[digit])
            chars.append(units[position])
            zero_pending = False
        elif chars and value % divisor:
            zero_pending = True
    return "".join(chars)


def _parse_date(raw: object, field: str, source_id: str) -> date:
    try:
        return date.fromisoformat(str(raw))
    except ValueError as exc:
        raise LegalSourceError(f"{source_id} 的 {field} 不是 ISO 日期") from exc


def _parse_ranges(raw: object, source_id: str) -> tuple[tuple[int, int], ...]:
    if not isinstance(raw, list) or not raw:
        raise LegalSourceError(f"{source_id} 未声明 included_ranges")
    ranges: list[tuple[int, int]] = []
    for item in raw:
        if not isinstance(item, list) or len(item) != 2:
            raise LegalSourceError(f"{source_id} 的 included_ranges 格式错误")
        start, end = item
        if not isinstance(start, int) or not isinstance(end, int) or start <= 0 or end < start:
            raise LegalSourceError(f"{source_id} 的条号范围无效：{item}")
        ranges.append((start, end))
    ordered = sorted(ranges)
    for previous, current in zip(ordered, ordered[1:]):
        if current[0] <= previous[1]:
            raise LegalSourceError(f"{source_id} 的条号范围重叠")
    return tuple(ordered)


def load_manifest(path: Path) -> tuple[SourceSpec, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LegalSourceError(f"无法读取法源清单：{path}") from exc
    if payload.get("schema_version") != 1 or not isinstance(payload.get("sources"), list):
        raise LegalSourceError("法源清单 schema_version 或 sources 无效")

    specs: list[SourceSpec] = []
    seen: set[str] = set()
    required = {
        "source_id", "title", "issuing_authority", "official_url", "file",
        "file_sha256", "included_ranges", "expected_article_count",
        "publication_date", "effective_date", "version_status", "retrieved_at",
    }
    for item in payload["sources"]:
        if not isinstance(item, dict) or required - item.keys():
            missing = sorted(required - item.keys()) if isinstance(item, dict) else sorted(required)
            raise LegalSourceError(f"法源清单缺少字段：{', '.join(missing)}")
        source_id = str(item["source_id"])
        if not _SOURCE_ID_RE.fullmatch(source_id) or source_id in seen:
            raise LegalSourceError(f"source_id 无效或重复：{source_id}")
        seen.add(source_id)
        host = (urlparse(str(item["official_url"])).hostname or "").lower()
        if host not in _OFFICIAL_HOSTS:
            raise LegalSourceError(f"{source_id} 使用非权威域名：{host or '空'}")
        file_sha256 = str(item["file_sha256"]).lower()
        if not _SHA256_RE.fullmatch(file_sha256):
            raise LegalSourceError(f"{source_id} 的 SHA-256 格式无效")
        expected_count = item["expected_article_count"]
        if not isinstance(expected_count, int) or expected_count <= 0:
            raise LegalSourceError(f"{source_id} 的 expected_article_count 无效")
        specs.append(SourceSpec(
            source_id=source_id,
            title=str(item["title"]).strip(),
            issuing_authority=str(item["issuing_authority"]).strip(),
            official_url=str(item["official_url"]).strip(),
            file=str(item["file"]).strip(),
            file_sha256=file_sha256,
            included_ranges=_parse_ranges(item["included_ranges"], source_id),
            expected_article_count=expected_count,
            publication_date=_parse_date(item["publication_date"], "publication_date", source_id),
            effective_date=_parse_date(item["effective_date"], "effective_date", source_id),
            version_status=str(item["version_status"]).strip(),
            retrieved_at=_parse_date(item["retrieved_at"], "retrieved_at", source_id),
        ))
    return tuple(specs)


def verify_source_file(spec: SourceSpec, base_dir: Path) -> str:
    root = base_dir.resolve()
    target = (root / spec.file).resolve()
    if not target.is_relative_to(root):
        raise LegalSourceError(f"{spec.source_id} 的文件路径位于法源目录之外")
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise LegalSourceError(f"{spec.source_id} 的法源文件不存在：{target}") from exc
    actual = hashlib.sha256(raw).hexdigest()
    if actual != spec.file_sha256:
        raise LegalSourceError(
            f"{spec.source_id} 的 SHA-256 不一致：expected={spec.file_sha256}, actual={actual}"
        )
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LegalSourceError(f"{spec.source_id} 的法源文件不是 UTF-8") from exc


def _in_ranges(article_number: int, ranges: tuple[tuple[int, int], ...]) -> bool:
    return any(start <= article_number <= end for start, end in ranges)


def parse_articles(spec: SourceSpec, text: str) -> tuple[ParsedArticle, ...]:
    parsed: list[ParsedArticle] = []
    seen: set[str] = set()
    chapter_title = ""
    current: dict | None = None

    def finish_current() -> None:
        if current is None:
            return
        content = "\n".join(current["lines"]).strip()
        if current["article_number"] in seen:
            raise LegalSourceError(f"{spec.source_id} 存在重复条号：{current['article_number']}")
        seen.add(current["article_number"])
        if _in_ranges(current["base"], spec.included_ranges):
            parsed.append(ParsedArticle(
                source_id=spec.source_id,
                article_number=current["article_number"],
                article_sort=current["base"] * 1000 + current["suffix"],
                chapter_title=current["chapter_title"],
                content=content,
                content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            ))

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _ARTICLE_RE.match(line)
        if match:
            finish_current()
            base = chinese_number_to_int(match.group("base"))
            suffix = chinese_number_to_int(match.group("suffix")) if match.group("suffix") else 0
            article_number = f"第{int_to_chinese_number(base)}条"
            if suffix:
                article_number += f"之{int_to_chinese_number(suffix)}"
            body = match.group("body").strip()
            current = {
                "base": base,
                "suffix": suffix,
                "article_number": article_number,
                "chapter_title": chapter_title,
                "lines": [f"{article_number}{(' ' + body) if body else ''}"],
            }
        elif _HEADING_RE.match(line):
            chapter_title = line
        elif current is not None:
            current["lines"].append(line)
    finish_current()
    return tuple(parsed)


def validate_article_set(spec: SourceSpec, articles: tuple[ParsedArticle, ...]) -> None:
    expected = {
        number
        for start, end in spec.included_ranges
        for number in range(start, end + 1)
    }
    actual = {article.article_sort // 1000 for article in articles}
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        labels = "、".join(f"第{int_to_chinese_number(number)}条" for number in missing[:10])
        raise LegalSourceError(f"{spec.source_id} 缺少条号：{labels}")
    if extra:
        labels = "、".join(f"第{int_to_chinese_number(number)}条" for number in extra[:10])
        raise LegalSourceError(f"{spec.source_id} 包含范围外条号：{labels}")
    if len(articles) != spec.expected_article_count:
        raise LegalSourceError(
            f"{spec.source_id} 条数不一致：expected={spec.expected_article_count}, "
            f"actual={len(articles)}"
        )


def _split_oversized_unit(text: str, max_chars: int) -> list[str]:
    sentences = [part for part in _SENTENCE_BOUNDARY_RE.split(text) if part]
    if len(sentences) == 1:
        return [text[index:index + max_chars] for index in range(0, len(text), max_chars)]
    parts: list[str] = []
    buffer = ""
    for sentence in sentences:
        if len(sentence) > max_chars:
            if buffer:
                parts.append(buffer)
                buffer = ""
            parts.extend(
                sentence[index:index + max_chars]
                for index in range(0, len(sentence), max_chars)
            )
        elif buffer and len(buffer) + len(sentence) > max_chars:
            parts.append(buffer)
            buffer = sentence
        else:
            buffer += sentence
    if buffer:
        parts.append(buffer)
    return parts


def split_structured_text(text: str, max_chars: int) -> tuple[str, ...]:
    """优先按换行款项、再按句界拆分，最后才按字符硬切。"""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if len(text) <= max_chars:
        return (text,)

    lines = text.splitlines()
    if len(lines) == 1:
        return tuple(_split_oversized_unit(text, max_chars))

    units: list[str] = []
    for line in lines:
        units.extend(
            [line] if len(line) <= max_chars else _split_oversized_unit(line, max_chars)
        )

    chunks: list[str] = []
    buffer = ""
    for unit in units:
        candidate = f"{buffer}\n{unit}" if buffer else unit
        if len(candidate) <= max_chars:
            buffer = candidate
        else:
            if buffer:
                chunks.append(buffer)
            buffer = unit
    if buffer:
        chunks.append(buffer)
    return tuple(chunks)


def split_legal_article(
    article: ParsedArticle,
    *,
    source_title: str,
    max_chars: int = 380,
) -> tuple[LegalChunk, ...]:
    pieces = split_structured_text(article.content, max_chars)
    count = len(pieces)
    chunks = []
    for index, content in enumerate(pieces):
        article_context = "" if content.startswith(article.article_number) else article.article_number
        context = [source_title, article.chapter_title, article_context, content]
        chunks.append(LegalChunk(
            article_key=(article.source_id, article.article_number),
            article_number=article.article_number,
            chunk_index=index,
            chunk_count=count,
            display_content=content,
            retrieval_text=" ".join(part for part in context if part),
        ))
    return tuple(chunks)
