"""将版本化规则命中映射为兼容的确定性风险。"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.services.audit.rules.executor import execute_rule
from app.services.audit.rules.registry import RuleRegistry, load_registry


@dataclass(frozen=True)
class DeterministicFinding:
    agent: str
    dimensions: tuple[str, ...]
    level: str
    category: str
    quote: str
    reason: str
    suggestion: str


_LEGACY_RULE_ORDER = {
    "LEGAL-PARTY-MISSING-001": 0,
    "LEGAL-SCOPE-MISSING-001": 1,
    "FIN-PAYMENT-TERMS-MISSING-001": 2,
    "LEGAL-INJURY-WAIVER-001": 3,
}
_LEGACY_MESSAGES = {
    "LEGAL-PARTY-MISSING-001": (
        "合同主体信息缺失",
        "合同相对方名称或身份信息留空，主体无法被唯一识别。",
        "补全乙方姓名、身份证号码等主体信息，并与签署人身份核验一致。",
    ),
    "LEGAL-SCOPE-MISSING-001": (
        "工作范围约定缺失",
        "项目名称留空，承揽事项的工作范围缺少明确边界。",
        "补充项目名称、具体工作内容、工作地点及可核验的交付标准。",
    ),
    "FIN-PAYMENT-TERMS-MISSING-001": (
        "付款日期及方式缺失",
        "付款日期和付款方式均留空，劳务费结算缺少可执行条件。",
        "明确每月付款截止日、付款账户或支付方式，并约定逾期处理机制。",
    ),
    "LEGAL-INJURY-WAIVER-001": (
        "人身损害免责责任风险",
        "条款试图将劳务过程中的人身损害责任全部排除或转由一方承担，存在免责无效及责任分配失衡风险。",
        "删除绝对免责表述，按过错、法定责任和保险保障重新约定人身损害责任。",
    ),
}


def find_deterministic_findings(
    contract_text: str,
    *,
    dimensions: list[str] | tuple[str, ...] | None = None,
) -> list[DeterministicFinding]:
    """返回命中规则的首个精确原文行；不推断原文无法证明的事实。"""
    selected = set(dimensions or ())
    findings: list[DeterministicFinding] = []
    rules = sorted(
        (
            rule
            for rule in _registry().rules
            if rule.rule_id in _LEGACY_RULE_ORDER
        ),
        key=lambda rule: _LEGACY_RULE_ORDER[rule.rule_id],
    )
    for rule in rules:
        if selected and not selected.intersection(rule.dimensions):
            continue
        result = execute_rule(rule, {"contract_text": contract_text})
        if result.status != "hit":
            continue
        category, reason, suggestion = _LEGACY_MESSAGES[rule.rule_id]
        findings.append(DeterministicFinding(
            agent=rule.agent,
            dimensions=rule.dimensions,
            level=rule.severity,
            category=category,
            quote=str(result.facts["quote"]),
            reason=reason,
            suggestion=suggestion,
        ))
    return findings


@lru_cache(maxsize=1)
def _registry() -> RuleRegistry:
    return load_registry()
