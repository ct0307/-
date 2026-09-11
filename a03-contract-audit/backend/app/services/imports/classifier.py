"""基于本地规则的合同类型初筛。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TypeSuggestion:
    suggested_type: str
    confidence: float
    evidence: list[str]


_FAMILIES = (
    (("采购", "购置", "供货", "设备"), ("采购",)),
    (("软件开发", "系统开发", "源代码", "技术开发"), ("软件开发", "技术开发")),
    (("劳动合同", "劳动关系", "试用期"), ("劳动",)),
    (("租赁", "出租方", "承租方"), ("租赁",)),
    (("保密", "商业秘密", "保密义务"), ("保密",)),
)


def classify_contract_type(
    *,
    filename: str,
    text: str,
    available_types: list[str],
) -> TypeSuggestion:
    """只在后台可用类型中选择最匹配项，并返回可解释的命中词。"""

    material = f"{filename}\n{text[:8000]}".lower()
    best_type = ""
    best_hits: list[str] = []
    for keywords, type_aliases in _FAMILIES:
        candidate = next(
            (
                value
                for value in available_types
                if any(alias in value for alias in type_aliases)
            ),
            "",
        )
        if not candidate:
            continue
        hits = [keyword for keyword in keywords if keyword.lower() in material]
        if len(hits) > len(best_hits):
            best_type, best_hits = candidate, hits

    if not best_hits:
        return TypeSuggestion("", 0.0, [])
    confidence = {1: 0.58, 2: 0.76}.get(len(best_hits), 0.90)
    return TypeSuggestion(best_type, confidence, best_hits)
