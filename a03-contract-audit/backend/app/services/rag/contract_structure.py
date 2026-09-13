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
class ContractWindow:
    window_id: str
    clause_ids: tuple[str, ...]
    text: str


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
            clause_id = match.group("clause_id").rstrip(".．、")
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
    units: list[tuple[str | None, str]] = []
    if chunks:
        first_start = chunks[0].anchor.char_start or 0
        preamble = text[:first_start].strip()
        if preamble:
            units.extend((None, part) for part in _split_oversized(preamble, max_chars))
    for chunk in chunks:
        units.extend(
            (chunk.clause_id, part)
            for part in _split_oversized(chunk.text, max_chars)
        )
    windows: list[ContractWindow] = []
    current_ids: list[str] = []
    current_parts: list[str] = []
    for clause_id, unit in units:
        candidate = "\n".join((*current_parts, unit))
        if current_parts and len(candidate) > max_chars:
            windows.append(_make_window(current_ids, current_parts))
            current_ids = []
            current_parts = []
        current_parts.append(unit)
        if clause_id and clause_id not in current_ids:
            current_ids.append(clause_id)
    if current_parts:
        windows.append(_make_window(current_ids, current_parts))
    return windows


def _chapter_before(chapters: list[tuple[int, str]], position: int) -> str:
    return next((title for offset, title in reversed(chapters) if offset < position), "")


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


def _make_window(clause_ids: list[str], parts: list[str]) -> ContractWindow:
    content = "\n".join(parts)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    return ContractWindow(
        window_id=f"window-{digest}",
        clause_ids=tuple(clause_ids),
        text=content,
    )
