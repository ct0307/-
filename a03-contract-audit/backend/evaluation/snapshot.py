"""从单次不可变字节快照解析评测输入并计算哈希。"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any


MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_JSONL_LINES = 100_000
MAX_JSONL_LINE_BYTES = 2 * 1024 * 1024
MAX_JSON_DEPTH = 128


@dataclass(frozen=True)
class FileSnapshot:
    data: bytes
    sha256: str


@dataclass(frozen=True)
class JsonObjectSnapshot:
    value: dict[str, Any]
    sha256: str


def _reject_non_finite(value: str) -> None:
    raise ValueError(f"JSON 不允许非有限数值: {value}")


def _validate_finite_json(value: Any, *, max_depth: int = MAX_JSON_DEPTH) -> None:
    stack: list[tuple[Any, str, int]] = [(value, "$", 0)]
    while stack:
        current, path, depth = stack.pop()
        if depth > max_depth:
            raise ValueError(f"JSON 嵌套深度超过上限 {max_depth}: {path}")
        if isinstance(current, float) and not math.isfinite(current):
            raise ValueError(f"JSON 不允许非有限数值: {path}")
        if isinstance(current, Mapping):
            stack.extend(
                (nested, f"{path}.{key}", depth + 1)
                for key, nested in current.items()
            )
        elif isinstance(current, list):
            stack.extend(
                (nested, f"{path}[{index}]", depth + 1)
                for index, nested in enumerate(current)
            )


def read_file_snapshot(path: Path, *, max_bytes: int = MAX_FILE_BYTES) -> FileSnapshot:
    path = Path(path)
    with path.open("rb") as source:
        data = source.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"{path.name} 超过大小上限 {max_bytes} 字节")
    return FileSnapshot(data=data, sha256=hashlib.sha256(data).hexdigest())


def read_jsonl_snapshot(
    path: Path,
    label: str,
    *,
    max_bytes: int = MAX_FILE_BYTES,
    max_lines: int = MAX_JSONL_LINES,
    max_line_bytes: int = MAX_JSONL_LINE_BYTES,
) -> tuple[list[dict[str, Any]], str]:
    snapshot = read_file_snapshot(path, max_bytes=max_bytes)
    raw_lines = snapshot.data.splitlines()
    if len(raw_lines) > max_lines:
        raise ValueError(f"{label} JSONL 超过行数上限 {max_lines}")
    records: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(raw_lines, 1):
        if len(raw_line) > max_line_bytes:
            raise ValueError(
                f"{label} JSONL 第 {line_number} 行超过大小上限 {max_line_bytes} 字节"
            )
        try:
            line = raw_line.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{label} JSONL 必须使用 UTF-8") from exc
        if not line.strip():
            continue
        try:
            record = json.loads(line, parse_constant=_reject_non_finite)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label} JSONL 第 {line_number} 行不是有效 JSON") from exc
        except RecursionError as exc:
            raise ValueError(f"{label} JSONL 嵌套深度超过解析上限") from exc
        if not isinstance(record, dict):
            raise ValueError(f"{label} JSONL 第 {line_number} 行必须是 JSON 对象")
        _validate_finite_json(record)
        records.append(record)
    if not records:
        raise ValueError(f"{label} JSONL 不能为空")
    return records, snapshot.sha256


def read_json_object_snapshot(
    path: Path, label: str, *, max_bytes: int = MAX_FILE_BYTES
) -> JsonObjectSnapshot:
    snapshot = read_file_snapshot(path, max_bytes=max_bytes)
    try:
        text = snapshot.data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} 必须使用 UTF-8") from exc
    try:
        value = json.loads(text, parse_constant=_reject_non_finite)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} 不是有效 JSON") from exc
    except RecursionError as exc:
        raise ValueError(f"{label} JSON 嵌套深度超过解析上限") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} 必须是 JSON 对象")
    _validate_finite_json(value)
    return JsonObjectSnapshot(value=value, sha256=snapshot.sha256)
