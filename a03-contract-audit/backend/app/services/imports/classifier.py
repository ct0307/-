"""基于本地规则的合同类型初筛。"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TypeCandidate:
    contract_type: str
    score: float
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class TypeSuggestion:
    suggested_type: str
    confidence: float
    evidence: list[str]
    candidates: tuple[TypeCandidate, ...] = ()
    auto_ready_eligible: bool = False


# 仅列主交易行为；保密、违约和争议条款不能作为其他合同的主交易证据。
_TRADE_SIGNALS: dict[str, tuple[str, ...]] = {
    "软件开发外包合同": ("软件开发", "系统开发", "源代码", "软件外包"),
    "技术服务合同": ("技术服务", "技术支持", "技术维护"),
    "采购合同": ("采购", "购置", "供货", "设备"),
    "销售合同": ("销售", "出售", "售卖"),
    "劳动合同": ("劳动关系", "试用期", "工资"),
    "租赁合同": ("租赁", "承租", "出租"),
    "保密协议": ("专项保密协议",),
    "合作协议": ("合作项目",),
    "服务协议": ("提供服务",),
    "框架协议": ("框架合作", "框架采购"),
    "技术开发合同": ("技术开发", "研发", "技术成果"),
    "合作合同": ("合作项目",),
    "服务合同": ("提供服务",),
    "劳务合同": ("劳务", "劳务报酬", "劳务人员"),
}

_TYPE_FAMILY_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("软件开发外包合同", ("软件开发", "软件外包", "系统开发")),
    ("技术服务合同", ("技术服务", "技术支持", "技术维护")),
    ("技术开发合同", ("技术开发", "研发")),
    ("采购合同", ("采购", "购置")),
    ("销售合同", ("销售", "出售")),
    ("劳动合同", ("劳动",)),
    ("劳务合同", ("劳务",)),
    ("租赁合同", ("租赁", "承租", "出租")),
    ("框架协议", ("框架",)),
    ("合作协议", ("合作协议",)),
    ("合作合同", ("合作合同",)),
    ("服务协议", ("服务协议",)),
    ("服务合同", ("服务合同",)),
    ("保密协议", ("保密协议",)),
)


def _family_for_type(contract_type: str) -> str | None:
    if contract_type in _TRADE_SIGNALS:
        return contract_type
    return next(
        (
            family
            for family, aliases in _TYPE_FAMILY_ALIASES
            if any(alias in contract_type for alias in aliases)
        ),
        None,
    )


def classify_contract_type(
    *,
    filename: str,
    text: str,
    available_types: list[str],
) -> TypeSuggestion:
    """在可用类型中排序候选，并仅把主交易证据标为自动就绪资格。"""

    name = Path(filename).stem.lower()
    lines = text[:8000].splitlines()
    first_line = next((line.strip().lower() for line in lines if line.strip()), "")
    title = first_line[:100]
    title_start = text.lower().find(title) if title else -1
    title_end = title_start + len(title) if title_start >= 0 else 0
    title_markers = ("附件", "条款")
    title_is_contract_type = (
        len(first_line) <= 64
        and not any(marker in first_line for marker in title_markers)
        and not any(mark in first_line for mark in ("。", "！", "？", "；", "，"))
        and any(value.lower() in first_line for value in available_types)
    )
    heading = text[title_end if title_is_contract_type else 0:1800].lower()
    body = text[1800:8000].lower()
    types = list(dict.fromkeys(available_types))
    scores: dict[str, float] = {value: 0.0 for value in types}
    evidence: dict[str, list[str]] = {value: [] for value in types}
    primary: set[str] = set()

    trusted_name = name if not any(marker in name for marker in title_markers) else ""
    trusted_title = title if title_is_contract_type else ""
    for source in (trusted_name, trusted_title):
        matches = [value for value in types if value.lower() in source]
        # 同一标题中较长的类型优先，避免“技术服务合同”同时命中“服务合同”。
        for value in matches:
            if any(value != longer and value in longer for longer in matches):
                continue
            scores[value] += 6
            evidence[value].append(value)
            primary.add(value)

    # 文件名中的受控交易别名可以产生建议，但不足以单独自动放行。
    for value in types:
        family = _family_for_type(value)
        if family and scores[value] == 0:
            name_hits = [
                keyword for keyword in _TRADE_SIGNALS[family]
                if keyword.lower() in trusted_name
            ]
            if name_hits:
                scores[value] += 6
                evidence[value].extend(name_hits)

    for value in types:
        family = _family_for_type(value)
        keywords = _TRADE_SIGNALS.get(family, ())
        hits = [keyword for keyword in keywords if keyword.lower() in heading or keyword.lower() in body]
        if not hits and value == "技术开发合同" and "软件开发外包合同" not in types:
            hits = [
                keyword for keyword in _TRADE_SIGNALS["软件开发外包合同"]
                if keyword in heading or keyword in body
            ]
        if hits:
            scores[value] += 3 if any(keyword.lower() in heading for keyword in hits) else 1
            evidence[value].extend(hits)
            primary.add(value)
        elif value == "保密协议" and any(word in heading or word in body for word in ("保密", "商业秘密")):
            scores[value] += 0.25
            evidence[value].append("保密")

    ranked = tuple(
        TypeCandidate(value, scores[value], tuple(dict.fromkeys(evidence[value])))
        for value in sorted(types, key=lambda item: (-scores[item], item))
        if scores[value] > 0
    )[:3]
    if not ranked:
        return TypeSuggestion("", 0.0, [])

    best = ranked[0]
    confidence = 0.20 if best.score <= 0.25 else 0.50 if best.score < 3 else 0.70 if best.score < 6 else 0.90
    margin = best.score - ranked[1].score if len(ranked) > 1 else best.score
    if margin < 4:
        confidence = min(confidence, 0.40 if margin == 0 else 0.55 if margin <= 1 else 0.70)
    return TypeSuggestion(
        best.contract_type, confidence, list(best.evidence), ranked,
        best.contract_type in primary and best.score >= 6 and margin >= 4,
    )
