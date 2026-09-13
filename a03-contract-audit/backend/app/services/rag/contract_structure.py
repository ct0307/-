"""合同条款结构化：稳定条款标识、标题路径与邻接关系。"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import re

from app.services.parser.extractor import DocumentBlock, SourceAnchor


_CHAPTER_RE = re.compile(
    r"^[ \t\u3000]*(第[一二三四五六七八九十百千万零〇两\d]+章[^\n]*)",
    re.MULTILINE,
)
_CLAUSE_RE = re.compile(
    r"^[ \t\u3000]*(?P<clause_id>"
    r"第[一二三四五六七八九十百千万零〇两\d]+条"
    r"|\d+(?:\.\d+)*[、.．]"
    r"|[一二三四五六七八九十]+、"
    r")(?P<title>[^\n]*)",
    re.MULTILINE,
)
_CLAUSE_ID_TRAILING = ".．、"


@dataclass(frozen=True)
class ContractChunk:
    chunk_id: str
    clause_id: str
    clause_path: tuple[str, ...]
    text: str
    anchor: SourceAnchor
    parent_chunk_id: str | None = None
    previous_chunk_id: str | None = None
    next_chunk_id: str | None = None
    block_type: str = "clause"
    source_anchors: tuple[SourceAnchor, ...] = ()


@dataclass(frozen=True)
class ContractWindowSegment:
    text: str
    clause_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ContractWindow:
    window_id: str
    clause_ids: tuple[str, ...]
    text: str
    segments: tuple[ContractWindowSegment, ...] = ()


def build_contract_chunks(
    text: str,
    *,
    blocks: tuple[DocumentBlock, ...] = (),
) -> list[ContractChunk]:
    """按顶层条款切分合同；无条款编号时按非空段落降级。"""
    matches = list(_CLAUSE_RE.finditer(text))
    chapters = [(match.start(), match.group(1).strip()) for match in _CHAPTER_RE.finditer(text)]
    chunks: list[ContractChunk] = []
    if matches:
        for index, match in enumerate(matches):
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            content = text[start:end].strip()
            clause_id = _normalize_clause_id(match.group("clause_id"))
            chapter = _chapter_before(chapters, start)
            chunks.append(_make_chunk(
                clause_id=clause_id,
                clause_path=tuple(value for value in (chapter, clause_id) if value),
                text=content,
                start=start,
                end=end,
                source_anchors=_anchors_for_range(text, blocks, start, end),
            ))
    else:
        for index, match in enumerate(re.finditer(r"\S(?:.*?\S)?(?=\n\s*\n|\Z)", text, re.DOTALL)):
            content = match.group(0).strip()
            if content:
                chunks.append(_make_chunk(
                    clause_id=f"段落{index + 1}",
                    clause_path=(f"段落{index + 1}",),
                    text=content,
                    start=match.start(),
                    end=match.end(),
                    source_anchors=_anchors_for_range(
                        text, blocks, match.start(), match.end()
                    ),
                ))
    return _link_neighbors(chunks)


def build_contract_windows(text: str, *, max_chars: int = 8000) -> list[ContractWindow]:
    """覆盖合同全文并尽量保持完整条款的审查窗口。"""
    if max_chars < 200:
        raise ValueError("审查窗口上限不能小于 200 字符")
    chunks = build_contract_chunks(text)
    units: list[ContractWindowSegment] = []
    if chunks:
        first_start = chunks[0].anchor.char_start or 0
        preamble = text[:first_start].strip()
        if preamble:
            units.extend(
                ContractWindowSegment(text=part)
                for part in _split_oversized(preamble, max_chars)
            )
    for chunk in chunks:
        units.extend(
            ContractWindowSegment(text=part, clause_ids=(chunk.clause_id,))
            for part in _split_oversized(chunk.text, max_chars)
        )
    windows: list[ContractWindow] = []
    current_segments: list[ContractWindowSegment] = []
    for unit in units:
        candidate = "\n".join(
            segment.text for segment in (*current_segments, unit)
        )
        if current_segments and len(candidate) > max_chars:
            windows.append(_make_window(current_segments))
            current_segments = []
        current_segments.append(unit)
    if current_segments:
        windows.append(_make_window(current_segments))
    return windows


def split_contract_window(window: ContractWindow) -> list[ContractWindow]:
    """沿父窗口内的稳定结构边界二分，并保留父窗口的文本和条款身份。"""
    text = window.text
    if not text.strip():
        return []

    if len(window.segments) >= 2:
        split_index = _choose_segment_split(window.segments)
        split_at = sum(
            len(segment.text) + 1
            for segment in window.segments[:split_index]
        )
        segment_groups = (
            window.segments[:split_index],
            window.segments[split_index:],
        )
        parts = (text[:split_at], text[split_at:])
        if any(not part.strip() for part in parts):
            return []
        return [
            _make_split_window(
                clause_ids=_segment_clause_ids(segments),
                text=part,
                segments=segments,
            )
            for segments, part in zip(segment_groups, parts, strict=True)
        ]

    clause_boundaries = [
        match.start()
        for match in _CLAUSE_RE.finditer(text)
        if text[:match.start()].strip() and text[match.start():].strip()
    ]
    boundaries = clause_boundaries or [
        match.end()
        for match in re.finditer(r"\n[ \t\u3000]*\n", text)
        if text[:match.end()].strip() and text[match.end():].strip()
    ]
    if not boundaries:
        return []

    split_at = min(boundaries, key=lambda offset: (abs(offset - len(text) / 2), offset))
    parts = (text[:split_at], text[split_at:])
    if any(not part.strip() for part in parts):
        return []

    parsed_clause_ids = [
        {
            _normalize_clause_id(match.group("clause_id"))
            for match in _CLAUSE_RE.finditer(part)
        }
        for part in parts
    ]
    child_clause_ids: list[list[str]] = [[], []]
    for clause_id in window.clause_ids:
        matches = [
            index
            for index, parsed_ids in enumerate(parsed_clause_ids)
            if clause_id in parsed_ids
        ]
        if len(matches) != 1:
            return []
        child_clause_ids[matches[0]].append(clause_id)

    return [
        _make_split_window(
            clause_ids=clause_ids,
            text=part,
        )
        for clause_ids, part in zip(child_clause_ids, parts, strict=True)
    ]


def _chapter_before(chapters: list[tuple[int, str]], position: int) -> str:
    return next((title for offset, title in reversed(chapters) if offset < position), "")


def _normalize_clause_id(value: str) -> str:
    return value.rstrip(_CLAUSE_ID_TRAILING)


def _choose_segment_split(segments: tuple[ContractWindowSegment, ...]) -> int:
    candidates = [
        index
        for index in range(1, len(segments))
        if segments[index - 1].clause_ids != segments[index].clause_ids
    ] or list(range(1, len(segments)))
    total_length = sum(len(segment.text) for segment in segments) + len(segments) - 1
    return min(
        candidates,
        key=lambda index: (
            abs(
                sum(len(segment.text) + 1 for segment in segments[:index])
                - total_length / 2
            ),
            index,
        ),
    )


def _segment_clause_ids(
    segments: tuple[ContractWindowSegment, ...],
) -> list[str]:
    return list(dict.fromkeys(
        clause_id
        for segment in segments
        for clause_id in segment.clause_ids
    ))


def _make_chunk(
    *,
    clause_id: str,
    clause_path: tuple[str, ...],
    text: str,
    start: int,
    end: int,
    source_anchors: tuple[SourceAnchor, ...] = (),
) -> ContractChunk:
    normalized = re.sub(r"\s+", "", text)
    digest = hashlib.sha256(f"{clause_id}\0{normalized}".encode("utf-8")).hexdigest()[:20]
    return ContractChunk(
        chunk_id=f"clause-{digest}",
        clause_id=clause_id,
        clause_path=clause_path,
        text=text,
        anchor=SourceAnchor(char_start=start, char_end=end),
        source_anchors=source_anchors,
    )


def _link_neighbors(chunks: list[ContractChunk]) -> list[ContractChunk]:
    return [
        replace(
            chunk,
            previous_chunk_id=chunks[index - 1].chunk_id if index else None,
            next_chunk_id=chunks[index + 1].chunk_id if index + 1 < len(chunks) else None,
        )
        for index, chunk in enumerate(chunks)
    ]


def _anchors_for_range(
    text: str,
    blocks: tuple[DocumentBlock, ...],
    start: int,
    end: int,
) -> tuple[SourceAnchor, ...]:
    cursor = 0
    anchors: list[SourceAnchor] = []
    for block in blocks:
        block_start = text.find(block.text, cursor)
        if block_start < 0:
            continue
        block_end = block_start + len(block.text)
        cursor = block_end
        if block_start < end and block_end > start:
            anchors.append(block.anchor)
    return tuple(anchors)


def _split_oversized(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    units = [
        unit.strip()
        for unit in re.split(r"(?<=。)|(?<=；)|\n+", text)
        if unit.strip()
    ]
    parts: list[str] = []
    buffer = ""
    for unit in units:
        if len(unit) > max_chars:
            if buffer:
                parts.append(buffer)
                buffer = ""
            parts.extend(unit[index:index + max_chars] for index in range(0, len(unit), max_chars))
            continue
        candidate = f"{buffer}\n{unit}".strip() if buffer else unit
        if len(candidate) > max_chars:
            parts.append(buffer)
            buffer = unit
        else:
            buffer = candidate
    if buffer:
        parts.append(buffer)
    return parts


def _make_window(segments: list[ContractWindowSegment]) -> ContractWindow:
    content = "\n".join(segment.text for segment in segments)
    clause_ids = _segment_clause_ids(tuple(segments))
    digest = _window_digest(clause_ids, content)
    return ContractWindow(
        window_id=f"window-{digest}",
        clause_ids=tuple(clause_ids),
        text=content,
        segments=tuple(segments),
    )


def _make_split_window(
    *,
    clause_ids: list[str],
    text: str,
    segments: tuple[ContractWindowSegment, ...] = (),
) -> ContractWindow:
    digest = _window_digest(clause_ids, text)
    return ContractWindow(
        window_id=f"window-{digest}",
        clause_ids=tuple(clause_ids),
        text=text,
        segments=segments,
    )


def _window_digest(clause_ids: list[str], text: str) -> str:
    identity = f"{'|'.join(clause_ids)}\0{text}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
