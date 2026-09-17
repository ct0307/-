"""版本化审查规则注册表测试。"""

import json

import pytest
from pydantic import ValidationError

from app.services.audit.rules.registry import RuleRegistry, load_registry
from app.services.audit.rules.schema import RuleDefinition


def _rule(**overrides) -> RuleDefinition:
    payload = {
        "rule_id": "FIN-PAYMENT-TOTAL-001",
        "version": "1.0.0",
        "name": "付款比例合计检查",
        "category": "numeric",
        "agent": "finance",
        "dimensions": ("payment",),
        "contract_types": ("采购合同",),
        "severity": "high",
        "handler": "payment_total",
        "manual_review_on_unclear": True,
    }
    payload.update(overrides)
    return RuleDefinition(**payload)


def test_registry_rejects_duplicate_rule_versions(tmp_path):
    payload = _rule().model_dump(mode="json")
    (tmp_path / "finance.json").write_text(
        json.dumps([payload, payload], ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="规则版本重复"):
        load_registry(tmp_path)


def test_registry_filters_by_agent_dimension_and_contract_type():
    registry = RuleRegistry([
        _rule(),
        _rule(
            rule_id="LEGAL-WAIVER-001",
            agent="legal",
            category="format",
            dimensions=("breach",),
            contract_types=(),
            handler="absolute_injury_waiver",
        ),
    ])

    rules = registry.select(
        agent="finance",
        dimensions={"payment"},
        contract_type="采购合同",
    )

    assert [rule.rule_id for rule in rules] == ["FIN-PAYMENT-TOTAL-001"]


def test_registry_allows_global_contract_type_and_preserves_input_order():
    registry = RuleRegistry([
        _rule(rule_id="FIN-GLOBAL-001", contract_types=()),
        _rule(rule_id="FIN-PURCHASE-001"),
    ])

    rules = registry.select(
        agent="finance",
        dimensions={"payment", "amount"},
        contract_type="采购合同",
    )

    assert [rule.rule_id for rule in rules] == [
        "FIN-GLOBAL-001", "FIN-PURCHASE-001"
    ]


def test_registry_rejects_unknown_handler():
    with pytest.raises(ValueError, match="未注册的规则处理器"):
        RuleRegistry([_rule(handler="module.function")])


def test_rule_definition_rejects_extra_fields():
    with pytest.raises(ValidationError):
        _rule(import_path="os.system")
