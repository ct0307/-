from __future__ import annotations

from types import SimpleNamespace

import pytest

import validate_document


def test_professional_profile_requires_exactly_23_images():
    assert validate_document.PROFILES["professional"]["images"] == (23, 23)


def test_professional_banned_phrases_include_table_text(monkeypatch, tmp_path):
    chapter_titles = [
        "第一章 项目概述",
        "第二章 需求分析",
        "第三章 总体方案设计",
        "第四章 核心功能详细设计",
        "第五章 关键技术实现方案",
        "第六章 数据安全与权限设计",
        "第七章 部署实施与运行保障",
        "第八章 测试与验收方案",
    ]
    required_facts = [
        "附录A 主要接口清单",
        "附录B 核心数据字典",
        "附录C 术语与缩略语",
        "附录D 参考文献",
        "[S01][S02][S03][S04][S05][S06]",
        "合规" * 12000,
    ]
    paragraphs = [SimpleNamespace(text=text) for text in chapter_titles + required_facts]
    tables = []
    for index in range(10):
        text = "当前状态" if index == 0 else "稳定内容"
        cell = SimpleNamespace(text=text)
        tables.append(SimpleNamespace(rows=[SimpleNamespace(cells=[cell])]))

    monkeypatch.setattr(
        validate_document,
        "Document",
        lambda _path: SimpleNamespace(paragraphs=paragraphs, tables=tables),
    )
    path = tmp_path / "professional.docx"
    path.write_bytes(b"not-a-zip")

    with pytest.raises(AssertionError, match="发现禁用表述：当前状态"):
        validate_document.validate_docx(path, "professional")
