"""评测快照必须拒绝所有层级的非有限 JSON 数值。"""
from __future__ import annotations

from io import BytesIO

import pytest

from evaluation.snapshot import (
    read_file_snapshot,
    read_json_object_snapshot,
    read_jsonl_snapshot,
)


def test_file_snapshot_never_requests_more_than_limit_plus_one(monkeypatch, tmp_path):
    requested_sizes: list[int] = []

    class RecordingSource(BytesIO):
        def read(self, size: int = -1) -> bytes:
            requested_sizes.append(size)
            return super().read(size)

    monkeypatch.setattr(
        type(tmp_path / "input.json"),
        "open",
        lambda *_args, **_kwargs: RecordingSource(b"x" * 32),
    )

    with pytest.raises(ValueError, match="大小上限"):
        read_file_snapshot(tmp_path / "input.json", max_bytes=8)

    assert requested_sizes == [9]


def test_jsonl_snapshot_enforces_line_count_and_line_size_limits(tmp_path):
    path = tmp_path / "input.jsonl"
    path.write_text('{"id":1}\n{"id":2}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="行数上限"):
        read_jsonl_snapshot(path, "测试输入", max_lines=1)
    with pytest.raises(ValueError, match="第 1 行超过大小上限"):
        read_jsonl_snapshot(path, "测试输入", max_line_bytes=4)


@pytest.mark.parametrize(
    "reader,content",
    [
        (read_jsonl_snapshot, '{"nested":{"value":1e999}}\n'),
        (read_json_object_snapshot, '{"nested":[0,1e999]}'),
    ],
)
def test_snapshot_rejects_overflowed_float_at_any_depth(tmp_path, reader, content):
    path = tmp_path / "input.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match="非有限"):
        reader(path, "测试输入")


@pytest.mark.parametrize("reader", [read_jsonl_snapshot, read_json_object_snapshot])
def test_snapshot_accepts_large_integer_and_ordinary_decimal(tmp_path, reader):
    path = tmp_path / "input.json"
    path.write_text(
        '{"large":123456789012345678901234567890,"decimal":0.125}\n',
        encoding="utf-8",
    )

    result = reader(path, "测试输入")
    value = result[0][0] if reader is read_jsonl_snapshot else result.value

    assert value == {
        "large": 123456789012345678901234567890,
        "decimal": 0.125,
    }


def test_snapshot_rejects_json_beyond_maximum_nesting_depth(tmp_path):
    path = tmp_path / "deep.json"
    path.write_text(
        '{"nested":' + "[" * 150 + "0" + "]" * 150 + "}", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="嵌套深度"):
        read_json_object_snapshot(path, "测试输入")


def test_snapshot_converts_parser_recursion_error_to_value_error(tmp_path):
    path = tmp_path / "too-deep.json"
    path.write_text(
        '{"nested":' + "[" * 1_100 + "0" + "]" * 1_100 + "}", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="嵌套深度"):
        read_json_object_snapshot(path, "测试输入")


def test_snapshot_accepts_ordinary_nested_json(tmp_path):
    path = tmp_path / "nested.json"
    path.write_text(
        '{"nested":' + "[" * 16 + "0" + "]" * 16 + "}", encoding="utf-8"
    )

    snapshot = read_json_object_snapshot(path, "测试输入")

    assert isinstance(snapshot.value["nested"], list)
