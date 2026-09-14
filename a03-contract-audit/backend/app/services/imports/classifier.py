"""基于本地规则的合同类型初筛。"""

import re
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

_MATERIAL_SEMANTICS = re.compile(r"审核|说明|模板|范本|复核|选用|记录|意见")
_BUSINESS_QUALIFIER = r"(?:设备|软件|系统|技术|服务|采购|销售|租赁|劳动|劳务|框架|合作)"


def _is_trusted_title_prefix(prefix: str) -> bool:
    if not prefix:
        return True
    if re.fullmatch(rf"{_BUSINESS_QUALIFIER}{{1,2}}", prefix):
        return True
    return bool(re.fullmatch(
        rf".{{1,32}}(?:公司|集团|中心|部门|项目|工程){_BUSINESS_QUALIFIER}{{0,2}}",
        prefix,
    ))


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


def _is_contract_title(line: str, available_types: list[str]) -> bool:
    normalized = "".join(line.lower().split())
    if (
        len(normalized) > 64
        or any(marker in normalized for marker in ("附件", "条款"))
        or _MATERIAL_SEMANTICS.search(normalized)
    ):
        return False
    suffix = r"(?:[（(][^）)\r\n]{1,20}[）)]|(?:v(?:ersion)?)?\d+(?:\.\d+)*版?)?"
    for value in available_types:
        match = re.fullmatch(
            rf"(?P<prefix>.*){re.escape(''.join(value.lower().split()))}{suffix}",
            normalized,
        )
        if match and _is_trusted_title_prefix(match.group("prefix")):
            return True
    return False


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
    title_markers = ("附件", "条款")
    title_is_contract_type = _is_contract_title(first_line, available_types)
    heading = text[:1800].lower()
    body = text[1800:8000].lower()
    types = list(dict.fromkeys(available_types))
    scores: dict[str, float] = {value: 0.0 for value in types}
    evidence: dict[str, list[str]] = {value: [] for value in types}
    primary: set[str] = set()
    headline_scored: set[str] = set()
    trusted_headline_scored: set[str] = set()

    trusted_name = name if _is_contract_title(name, types) else ""
    material_name = bool(_MATERIAL_SEMANTICS.search(name))
    material_title = bool(_MATERIAL_SEMANTICS.search(first_line))
    trusted_title = title if title_is_contract_type else ""
    for source in (trusted_name, trusted_title):
        matches = [value for value in types if value.lower() in source]
        # 同一标题中较长的类型优先，避免“技术服务合同”同时命中“服务合同”。
        for value in matches:
            if any(value != longer and value in longer for longer in matches):
                continue
            if value in headline_scored:
                continue
            if not ((source == trusted_name and material_name) or (source == trusted_title and material_title)):
                scores[value] += 6
            evidence[value].append(value)
            if scores[value] > 0:
                primary.add(value)
                headline_scored.add(value)
                trusted_headline_scored.add(value)

    # 文件名中的受控交易别名可以产生建议，但不足以单独自动放行。
    for value in types:
        family = _family_for_type(value)
        if family and scores[value] == 0:
            name_hits = [
                keyword for keyword in _TRADE_SIGNALS[family]
                if keyword.lower() in name
            ]
            if name_hits and not material_name:
                scores[value] += 6
                evidence[value].extend(name_hits)
                headline_scored.add(value)

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
            if value not in headline_scored:
                scores[value] += 3 if any(keyword.lower() in heading for keyword in hits) else 1
            evidence[value].extend(hits)
            primary.add(value)
        elif value == "保密协议" and any(word in heading or word in body for word in ("保密", "商业秘密")):
            if value not in headline_scored:
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
    eligible = (
        best.contract_type in trusted_headline_scored
        and best.contract_type in primary
        and best.score >= 6
        and margin >= 4
    )
    if material_name or material_title:
        eligible = False
    return TypeSuggestion(
        best.contract_type, confidence, list(best.evidence), ranked,
        eligible,
    )
