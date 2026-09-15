"""无需模型推理即可从合同原文直接证明的基础风险。"""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


@dataclass(frozen=True)
class DeterministicFinding:
    agent: str
    dimensions: tuple[str, ...]
    level: str
    category: str
    quote: str
    reason: str
    suggestion: str


@dataclass(frozen=True)
class _Rule:
    agent: str
    dimensions: tuple[str, ...]
    level: str
    category: str
    pattern: re.Pattern[str]
    reason: str
    suggestion: str


_BLANK = r"(?:\s|[_＿]){2,}"
_RULES = (
    _Rule(
        agent="legal",
        dimensions=("legal",),
        level="high",
        category="合同主体信息缺失",
        pattern=re.compile(r"(?:乙方(?:（[^）]{0,20}）)?|身份证号码)\s*[：:]\s*$"),
        reason="合同相对方名称或身份信息留空，主体无法被唯一识别。",
        suggestion="补全乙方姓名、身份证号码等主体信息，并与签署人身份核验一致。",
    ),
    _Rule(
        agent="legal",
        dimensions=("legal",),
        level="medium",
        category="工作范围约定缺失",
        pattern=re.compile(rf"甲方将{_BLANK}项目"),
        reason="项目名称留空，承揽事项的工作范围缺少明确边界。",
        suggestion="补充项目名称、具体工作内容、工作地点及可核验的交付标准。",
    ),
    _Rule(
        agent="finance",
        dimensions=("payment",),
        level="medium",
        category="付款日期及方式缺失",
        pattern=re.compile(rf"每月{_BLANK}日前以{_BLANK}方式(?:支付|结算)"),
        reason="付款日期和付款方式均留空，劳务费结算缺少可执行条件。",
        suggestion="明确每月付款截止日、付款账户或支付方式，并约定逾期处理机制。",
    ),
    _Rule(
        agent="legal",
        dimensions=("breach", "risk"),
        level="high",
        category="人身损害免责责任风险",
        pattern=re.compile(
            r"(?:不承担.*(?:工伤|意外伤害).*(?:任何|全部).*责任|"
            r"人身损害.*一切后果.*自行承担)"
        ),
        reason="条款试图将劳务过程中的人身损害责任全部排除或转由一方承担，存在免责无效及责任分配失衡风险。",
        suggestion="删除绝对免责表述，按过错、法定责任和保险保障重新约定人身损害责任。",
    ),
)


def find_deterministic_findings(
    contract_text: str,
    *,
    dimensions: list[str] | tuple[str, ...] | None = None,
) -> list[DeterministicFinding]:
    """返回命中规则的首个精确原文行；不推断原文无法证明的事实。"""
    selected = set(dimensions or ())
    lines = [line.strip() for line in contract_text.splitlines() if line.strip()]
    normalized_lines = [unicodedata.normalize("NFKC", line) for line in lines]
    normalized_text, source_indexes = _normalize_with_source_indexes(contract_text)
    findings: list[DeterministicFinding] = []
    for rule in _RULES:
        if selected and not selected.intersection(rule.dimensions):
            continue
        match_index = next(
            (
                index
                for index, normalized in enumerate(normalized_lines)
                if rule.pattern.search(normalized)
            ),
            None,
        )
        quote: str
        if match_index is not None:
            quote = lines[match_index]
        else:
            match = rule.pattern.search(normalized_text)
            if match is None:
                continue
            source_start = source_indexes[match.start()]
            source_end = source_indexes[match.end() - 1] + 1
            quote = contract_text[source_start:source_end]
        findings.append(DeterministicFinding(
            agent=rule.agent,
            dimensions=rule.dimensions,
            level=rule.level,
            category=rule.category,
            quote=quote,
            reason=rule.reason,
            suggestion=rule.suggestion,
        ))
    return findings


def _normalize_with_source_indexes(text: str) -> tuple[str, list[int]]:
    normalized_parts: list[str] = []
    source_indexes: list[int] = []
    for source_index, character in enumerate(text):
        normalized = unicodedata.normalize("NFKC", character)
        normalized_parts.append(normalized)
        source_indexes.extend([source_index] * len(normalized))
    return "".join(normalized_parts), source_indexes
