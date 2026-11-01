"""从项目内 JSON 加载版本化规则，禁止配置任意导入路径。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from app.services.audit.rules.schema import RuleDefinition


DEFINITIONS_DIR = Path(__file__).with_name("definitions")

REGISTERED_HANDLERS = frozenset({
    "party_missing",
    "work_scope_missing",
    "payment_terms_missing",
    "absolute_injury_waiver",
    "payment_total",
    "amount_consistency",
    "payee_consistency",
    "date_order",
    "payment_deadline_conflict",
})


class RuleRegistry:
    def __init__(self, rules: Iterable[RuleDefinition]) -> None:
        self._rules = tuple(rules)
        seen: set[tuple[str, str]] = set()
        for rule in self._rules:
            key = (rule.rule_id, rule.version)
            if key in seen:
                raise ValueError(f"规则版本重复: {rule.rule_id}@{rule.version}")
            seen.add(key)
            if rule.handler not in REGISTERED_HANDLERS:
                raise ValueError(f"未注册的规则处理器: {rule.handler}")

    @property
    def rules(self) -> tuple[RuleDefinition, ...]:
        return self._rules

    def select(
        self,
        *,
        agent: str,
        dimensions: set[str],
        contract_type: str,
    ) -> tuple[RuleDefinition, ...]:
        return tuple(
            rule
            for rule in self._rules
            if rule.agent == agent
            and bool(dimensions.intersection(rule.dimensions))
            and (
                not rule.contract_types
                or contract_type in rule.contract_types
            )
        )


def load_registry(directory: Path = DEFINITIONS_DIR) -> RuleRegistry:
    rules: list[RuleDefinition] = []
    for path in sorted(Path(directory).glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"规则定义文件必须是数组: {path.name}")
        rules.extend(RuleDefinition.model_validate(item) for item in payload)
    return RuleRegistry(rules)
