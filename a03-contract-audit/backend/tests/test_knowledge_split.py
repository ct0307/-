# 知识库智能切片单元测试：条文识别 / 段落降级 / 清洗 / 去重键
from app.api.v1.endpoints.knowledge import (
    _chunk_key,
    _clean_lines,
    _smart_split,
    _split_by_article,
)


def test_article_split_basic():
    """法规文本按「第X条」切割，条数正确，每片以条文标记开头。"""
    text = """第一条 为了保护合同当事人的合法权益，制定本法。
第二条 本法所称合同是民事主体之间设立、变更、终止民事法律关系的协议。
第三条 当事人订立合同应当遵循公平原则。"""
    result = _smart_split(text)
    assert result.mode == "article"
    assert result.article_count == 3
    assert len(result.chunks) == 3
    assert result.chunks[0].startswith("第一条")
    assert result.chunks[1].startswith("第二条")
    assert result.chunks[2].startswith("第三条")


def test_article_split_arabic_number():
    """阿拉伯数字条号也能识别。"""
    text = "第1条 甲方义务如下。\n第2条 乙方义务如下。\n第3条 违约责任约定。"
    result = _smart_split(text)
    assert result.mode == "article"
    assert result.article_count == 3


def test_article_split_multiline_content():
    """单条法条含多行内容时，内容完整归入该条，不被拆散。"""
    text = """第五百八十五条 当事人可以约定一方违约时应当支付违约金。
约定的违约金过分高于造成的损失的，人民法院可以适当减少。
当事人就迟延履行约定违约金的，违约方支付违约金后还应履行债务。
第五百八十六条 当事人可以约定定金作为债权担保。"""
    result = _smart_split(text)
    assert result.mode == "article"
    assert result.article_count == 2
    # 第一条应包含全部三行内容
    assert "适当减少" in result.chunks[0]
    assert "还应履行债务" in result.chunks[0]
    assert result.chunks[1].startswith("第五百八十六条")


def test_single_article_falls_back_to_paragraph():
    """只有一条「第X条」时不触发条文模式，走段落切割。"""
    text = "第一条 独立条款。\n\n这是另一个普通段落，没有条号标记。"
    result = _smart_split(text)
    assert result.mode == "paragraph"


def test_paragraph_split():
    """非法规文本按空行分段。"""
    text = "风险规则：违约金过低。建议不低于合同金额10%。\n\n付款条件应明确验收标准、付款时限、开票要求和逾期责任。"
    result = _smart_split(text)
    assert result.mode == "paragraph"
    assert len(result.chunks) == 2
    assert result.paragraph_count == 2


def test_long_paragraph_split_by_sentence():
    """超长段落按句号二次切割。"""
    sent = "这是一个很长的句子用来测试切割逻辑。" * 20  # 每句约18字，20句约360字
    text = sent + sent  # 约720字，超过500上限
    result = _smart_split(text)
    assert result.mode == "paragraph"
    assert len(result.chunks) >= 2
    assert all(len(c) <= 600 for c in result.chunks)  # 留余量，句子边界不精确切


def test_clean_removes_page_numbers():
    """页码行、纯符号行被清洗。"""
    text = """第一条 正文内容。
- 3 -
第二条 更多内容。
第 5 页
第三条 结尾内容。
========"""
    cleaned = _clean_lines(text)
    assert "- 3 -" not in cleaned
    assert "第 5 页" not in cleaned
    assert "========" not in cleaned
    assert "第一条 正文内容。" in cleaned


def test_clean_removes_short_fragments():
    """清洗后的短碎片在切片阶段被过滤。"""
    text = "第一条 这是一条有效的法条内容足够长。\n第二条 另一条同样有效的完整内容。\n\n啊"
    result = _smart_split(text)
    # "啊" 这种 <8 字碎片不应入库
    assert all(len(c) >= 8 for c in result.chunks)


def test_empty_text():
    """空文本返回 empty 模式，无切片。"""
    result = _smart_split("   \n\n  \n")
    assert result.mode == "empty"
    assert result.chunks == []


def test_chunk_key_stable_and_distinct():
    """去重键：同 source+content 一致，不同则相异。"""
    k1 = _chunk_key("《民法典》", "第一条内容")
    k2 = _chunk_key("《民法典》", "第一条内容")
    k3 = _chunk_key("《民法典》", "第二条内容")
    k4 = _chunk_key("《合同法》", "第一条内容")
    assert k1 == k2
    assert k1 != k3
    assert k1 != k4


def test_split_by_article_returns_none_when_no_articles():
    """无条文标记时返回 None（触发降级）。"""
    assert _split_by_article("普通文本，没有任何条号。") is None


def test_cross_reference_not_split():
    """条文正文里的交叉引用（句中「第X条」）不被误判为新条文边界。"""
    text = """第五百零九条 当事人应当按照约定全面履行自己的义务，依照本法第五百一十条的规定确定。
第五百一十条 合同生效后，当事人就质量约定不明确的，可以协议补充。"""
    result = _smart_split(text)
    assert result.mode == "article"
    # 只有 2 条真实条文，句中的「第五百一十条」引用不算
    assert result.article_count == 2
    assert len(result.chunks) == 2
    # 第一条应完整包含句中引用，不被拆断
    assert "依照本法第五百一十条的规定确定" in result.chunks[0]


def test_article_with_leading_whitespace():
    """行首带缩进的条文仍能识别（全角空格/制表符）。"""
    text = "　第一条 缩进条文一。\n\t第二条 缩进条文二。\n第三条 正常条文三。"
    result = _smart_split(text)
    assert result.mode == "article"
    assert result.article_count == 3
