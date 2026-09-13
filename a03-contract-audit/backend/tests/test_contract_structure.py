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
