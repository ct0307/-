import pytest


def test_contract_chunks_have_stable_clause_ids_and_neighbors():
    from app.services.rag.contract_structure import build_contract_chunks

    text = """第一章 合同履行
第一条 甲方负责提供项目资料。
第二条 乙方应在十个工作日内完成交付。
第三条 甲方应在验收后十日内付款。"""

    chunks = build_contract_chunks(text)

    assert [chunk.clause_id for chunk in chunks] == ["第一条", "第二条", "第三条"]
    assert all(chunk.clause_path[0] == "第一章 合同履行" for chunk in chunks)
    assert chunks[0].previous_chunk_id is None
    assert chunks[0].next_chunk_id == chunks[1].chunk_id
    assert chunks[1].previous_chunk_id == chunks[0].chunk_id
    assert chunks[1].next_chunk_id == chunks[2].chunk_id
    assert chunks[2].next_chunk_id is None


def test_contract_chunk_ids_are_reproducible():
    from app.services.rag.contract_structure import build_contract_chunks

    text = "第一条 合同标的为软件开发。\n第二条 项目验收后支付全部款项。"

    first = build_contract_chunks(text)
    second = build_contract_chunks(text)

    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in second]


def test_contract_chunks_inherit_all_overlapping_page_anchors():
    from app.services.parser.extractor import DocumentBlock, SourceAnchor
    from app.services.rag.contract_structure import build_contract_chunks

    blocks = (
        DocumentBlock(
            block_id="pdf-page-1",
            block_type="page_text",
            text="第一条 付款安排",
            anchor=SourceAnchor(page_number=1),
        ),
        DocumentBlock(
            block_id="pdf-page-2",
            block_type="page_text",
            text="验收后十日付款。",
            anchor=SourceAnchor(page_number=2),
        ),
    )
    text = "\n".join(block.text for block in blocks)

    chunks = build_contract_chunks(text, blocks=blocks)

    assert [anchor.page_number for anchor in chunks[0].source_anchors] == [1, 2]


def test_contract_windows_cover_long_contract_without_cutting_off_tail():
    from app.services.rag.contract_structure import build_contract_windows

    text = "\n".join(
        f"第{index}条 " + (f"第{index}条内容" * 25)
        for index in range(1, 31)
    )

    windows = build_contract_windows(text, max_chars=900)

    assert len(windows) > 1
    assert all(len(window.text) <= 900 for window in windows)
    assert "第30条内容" in windows[-1].text
    assert {clause_id for window in windows for clause_id in window.clause_ids} == {
        f"第{index}条" for index in range(1, 31)
    }


def test_contract_windows_keep_preamble_before_first_numbered_clause():
    from app.services.rag.contract_structure import build_contract_windows

    text = """软件开发合同
甲方：测试科技有限公司
乙方：交付技术有限公司
第一条 项目内容为合同审查系统开发。
第二条 验收后十日内支付款项。"""

    windows = build_contract_windows(text, max_chars=500)

    assert "软件开发合同" in windows[0].text
    assert "甲方：测试科技有限公司" in windows[0].text
    assert windows[0].clause_ids == ("第一条", "第二条")


def test_split_contract_window_preserves_text_clauses_and_stable_ids():
    from app.services.rag.contract_structure import (
        ContractWindow,
        split_contract_window,
    )

    text = """第一条 项目范围为合同审查。
第二条 乙方应按期交付成果。
第三条 甲方应在验收后付款。
第四条 双方应保护商业秘密。"""
    parent = ContractWindow(
        window_id="window-parent",
        clause_ids=("第一条", "第二条", "第三条", "第四条"),
        text=text,
    )

    first = split_contract_window(parent)
    second = split_contract_window(parent)

    assert len(first) >= 2
    assert "".join(child.text for child in first) == parent.text
    assert tuple(
        clause_id for child in first for clause_id in child.clause_ids
    ) == parent.clause_ids
    assert [child.window_id for child in first] == [
        child.window_id for child in second
    ]
    assert all(child.window_id != parent.window_id for child in first)
    assert all(child.text.strip() for child in first)


def test_split_contract_window_uses_parent_relative_clause_boundaries():
    from app.services.rag.contract_structure import (
        ContractWindow,
        build_contract_chunks,
        split_contract_window,
    )

    text = """合同名称：软件开发合同
第一条 项目内容为开发审查系统。
第二条 乙方应在十日内完成交付。
第三条 甲方在验收后支付款项。"""
    parent = ContractWindow(
        window_id="window-with-preamble",
        clause_ids=("第一条", "第二条", "第三条"),
        text=text,
    )

    children = split_contract_window(parent)
    rebuilt_chunks = [
        chunk
        for child in children
        for chunk in build_contract_chunks(child.text)
    ]

    assert "".join(child.text for child in children) == text
    assert [chunk.clause_id for chunk in rebuilt_chunks] == list(parent.clause_ids)
    assert all(
        child.text.lstrip().startswith(("合同名称", "第一条", "第二条", "第三条"))
        for child in children
    )


def test_split_contract_window_returns_empty_when_no_stable_boundary_exists():
    from app.services.rag.contract_structure import ContractWindow, split_contract_window

    parent = ContractWindow(
        window_id="window-atomic",
        clause_ids=("第一条",),
        text="第一条 这是不能继续拆分的单一条款。",
    )

    assert split_contract_window(parent) == []


def test_split_contract_window_does_not_treat_clause_reference_as_heading():
    from app.services.rag.contract_structure import ContractWindow, split_contract_window

    parent = ContractWindow(
        window_id="window-reference",
        clause_ids=("第一条", "第二条"),
        text=(
            "第一条 付款安排如第二条另有约定，从其约定。\n"
            "第二条 乙方应在验收后十日内交付成果。"
        ),
    )

    children = split_contract_window(parent)

    assert [child.clause_ids for child in children] == [("第一条",), ("第二条",)]


@pytest.mark.parametrize(
    ("first_heading", "second_heading", "expected_ids"),
    [
        ("一、", "二、", ("一", "二")),
        ("1、", "2、", ("1", "2")),
    ],
)
def test_split_real_window_normalizes_enumeration_ids_consistently(
    first_heading,
    second_heading,
    expected_ids,
):
    from app.services.rag.contract_structure import (
        build_contract_windows,
        split_contract_window,
    )

    text = (
        f"{first_heading}付款安排参照{second_heading}交付约定执行。\n"
        f"{second_heading}乙方应在验收后十日内交付成果。"
    )
    windows = build_contract_windows(text, max_chars=500)

    assert len(windows) == 1
    assert windows[0].clause_ids == expected_ids

    children = split_contract_window(windows[0])

    assert [child.clause_ids for child in children] == [
        (expected_ids[0],),
        (expected_ids[1],),
    ]


def test_split_real_unnumbered_window_uses_preserved_paragraph_segments():
    from app.services.rag.contract_structure import (
        build_contract_windows,
        split_contract_window,
    )

    source = (
        "项目范围包括合同审查与风险提示。\n\n"
        "乙方应在十个工作日内完成交付。\n\n"
        "甲方应在验收后十日内支付款项。"
    )
    windows = build_contract_windows(source, max_chars=500)

    assert len(windows) == 1
    assert windows[0].clause_ids == ("段落1", "段落2", "段落3")

    children = split_contract_window(windows[0])

    assert len(children) >= 2
    assert "".join(child.text for child in children) == windows[0].text
    assert tuple(
        clause_id for child in children for clause_id in child.clause_ids
    ) == windows[0].clause_ids
    assert all(child.clause_ids for child in children)


def test_split_manual_window_refuses_to_guess_unresolved_clause_ids():
    from app.services.rag.contract_structure import ContractWindow, split_contract_window

    parent = ContractWindow(
        window_id="window-unresolved-ids",
        clause_ids=("外部ID-A", "外部ID-B"),
        text="第一条 项目范围。\n第二条 付款安排。",
    )

    assert split_contract_window(parent) == []
