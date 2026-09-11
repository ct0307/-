"""风险结论与检索依据之间的保守支持关系校验。"""

from __future__ import annotations

import re
from dataclasses import dataclass


SUPPORT_VALIDATOR_VERSION = "rules-v2"

_ABSENCE_MARKERS = (
    "全文未检出",
    "未检出",
    "未约定",
    "未明确",
    "缺失",
    "缺少",
    "不存在",
    "没有",
    "无相关",
)

_GENERIC_TERMS = (
    "合同",
    "条款",
    "责任",
    "风险",
    "规定",
    "约定",
    "相关",
    "内容",
    "需要",
    "审查",
    "可能",
    "存在",
)

_GENERIC_FRAGMENTS = {
    "contract",
    "clause",
    "liability",
    "risk",
    "review",
}


@dataclass(frozen=True)
class SupportValidation:
    """支持关系校验的可持久化结果。"""

    status: str
    reason: str
    version: str = SUPPORT_VALIDATOR_VERSION


def validate_support_relation(
    risk: dict,
    sources: list[dict] | tuple[dict, ...],
) -> SupportValidation:
    """以确定性规则判断依据是否明确支持候选风险。

    规则故意偏保守：缺失类风险不能由正向法条证明；其余风险至少需要两个
    非空语义片段同时出现在可信来源中。无法判断时返回 ``unclear``，由人工复核。
    """
    reliable_sources = [
        source
        for source in sources
        if source.get("reliable") is True
        and str(source.get("content", "")).strip()
        and str(source.get("source", "")).strip()
    ]
    if not reliable_sources:
        return SupportValidation("unclear", "没有可用的可信来源")

    risk_text = " ".join(
        str(risk.get(field, ""))
        for field in ("category", "original_text", "risk_reason")
    )
    if any(marker in risk_text for marker in _ABSENCE_MARKERS):
        return SupportValidation("unclear", "缺失类风险不能仅由正向依据证明")

    category_fragments = _meaningful_fragments(str(risk.get("category", "")))
    source_text = " ".join(str(source["content"]) for source in reliable_sources)
    matched_category = {
        fragment for fragment in category_fragments if fragment in source_text.lower()
    }
    if not matched_category:
        return SupportValidation(
            "unclear",
            "未发现足够语义重叠：未命中有效风险类别锚点，需人工核验",
        )

    risk_fragments = set().union(
        *(
            _meaningful_fragments(str(risk.get(field, "")))
            for field in ("category", "original_text", "risk_reason")
        )
    )
    matched = {fragment for fragment in risk_fragments if fragment in source_text.lower()}
    if len(matched) >= 2:
        return SupportValidation("supported", "风险类别与依据内容存在明确语义重叠")
    return SupportValidation("unclear", "未发现足够语义重叠，需人工核验")


def _fragments(text: str) -> set[str]:
    normalized = text.lower()
    fragments: set[str] = set()
    for match in re.finditer(r"[\u4e00-\u9fff]+", normalized):
        value = match.group(0)
        fragments.update(value[index:index + 2] for index in range(len(value) - 1))
    fragments.update(re.findall(r"[a-z0-9]{3,}", normalized))
    return fragments


def _meaningful_fragments(text: str) -> set[str]:
    normalized = text.lower()
    for term in _GENERIC_TERMS:
        normalized = normalized.replace(term, " ")
    return _fragments(normalized) - _GENERIC_FRAGMENTS
