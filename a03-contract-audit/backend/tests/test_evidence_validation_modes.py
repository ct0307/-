"""确定性支持必须有有限规则，不能以字词重叠采信结论。"""
import pytest

from app.services.audit.evidence_validation import verify_support as _verify_support


def verify_support(risk, sources, **kwargs):
    kwargs.setdefault("contract_text", risk.get("original_text"))
    return _verify_support(risk, sources, **kwargs)


def _risk(**changes):
    value = {
        "category": "人身损害免责责任风险",
        "original_text": "甲方不承担乙方在提供劳务过程中的工伤、意外伤害等任何责任。",
        "risk_reason": "绝对免责表述存在无效风险",
        "original_text_verified": True,
    }
    value.update(changes)
    return value


def _source(**changes):
    value = {
        "content": "合同中的下列免责条款无效：（一）造成对方人身损害的；（二）因故意或者重大过失造成对方财产损失的。",
        "source": "中华人民共和国民法典",
        "article_number": "第五百零六条",
        "reliable": True,
        "applicability_status": "applicable",
    }
    value.update(changes)
    return value


def test_deterministic_support_is_versioned_and_bound_to_a_finite_rule():
    result = verify_support(_risk(), [_source()], mode="deterministic")
    assert result.status == "supported"
    assert result.mode == "deterministic"
    assert result.version == "support-deterministic-v1"
    assert result.failed_stage == "none"
    assert result.evidence_relations[0]["rule_id"] == "LEGAL-INJURY-WAIVER-001"
    assert result.evidence_relations[0]["rule_version"] == "1.0.0"


@pytest.mark.parametrize("changes", [
    {"category": ""},
    {"category": "违约金过高"},
    {"risk_reason": "未约定人身损害免责"},
    {"original_text": "甲方承担乙方工作过程中的工伤、意外伤害等全部责任。"},
    {"original_text": "若伤害系乙方故意造成，甲方不承担乙方工伤、意外伤害等任何责任。"},
    {"original_text": "乙方要求删除：甲方不承担乙方工伤、意外伤害等任何责任。"},
    {"original_text": "甲方不承担乙方工伤、意外伤害等任何责任，但法律另有规定除外。"},
    {"original_text": "甲方不承担甲方在提供劳务过程中的工伤、意外伤害等任何责任。"},
])
def test_word_overlap_absence_negation_and_conditions_remain_unclear(changes):
    result = verify_support(_risk(**changes), [_source()], mode="deterministic")
    assert result.status == "unclear"
    assert result.reason_code == "DETERMINISTIC_RULE_NOT_PROVEN"


@pytest.mark.parametrize("changes", [
    {"source": "某内部规则"},
    {"article_number": "第五百八十五条"},
    {"content": "人身损害合同责任风险需要审查，付款期限等。"},
    {"content": "造成对方人身损害的免责条款有效。"},
    {"content": "合同中的下列免责条款无效：（一）造成对方人身损害的。"},
])
def test_wrong_law_article_or_incomplete_source_cannot_support(changes):
    result = verify_support(_risk(), [_source(**changes)], mode="deterministic")
    assert result.status == "unclear"
    assert result.reason_code == "DETERMINISTIC_SOURCE_NOT_PROVEN"


@pytest.mark.parametrize(("risk_changes", "source_changes", "stage"), [
    ({"original_text_verified": False}, {}, "original"),
    ({}, {"reliable": False}, "authority"),
    ({}, {"applicability_status": "expired"}, "applicability"),
])
def test_finite_rule_cannot_skip_evidence_gates(risk_changes, source_changes, stage):
    result = verify_support(_risk(**risk_changes), [_source(**source_changes)], mode="deterministic")
    assert result.status == "unclear"
    assert result.failed_stage == stage


def test_manual_only_cannot_be_overridden_by_an_injected_verifier():
    result = verify_support(_risk(), [_source()], mode="manual_only", semantic_verifier=lambda *_: "supported")
    assert result.status == "unclear"
    assert result.reason_code == "SEMANTIC_VERIFIER_UNAVAILABLE"


def test_deterministic_rule_failure_degrades_to_manual(monkeypatch):
    from app.services.audit.rules import registry
    monkeypatch.setattr(registry, "load_registry", lambda: (_ for _ in ()).throw(ValueError("bad rule")))
    result = verify_support(_risk(), [_source()], mode="deterministic")
    assert result.status == "unclear"
    assert result.reason_code == "DETERMINISTIC_VERIFIER_UNAVAILABLE"


def test_unsupported_validation_mode_is_rejected():
    with pytest.raises(ValueError):
        verify_support(_risk(), [_source()], mode="unknown")


@pytest.mark.parametrize("context", [None,
    "以下为已删除的无效示例：" + _risk()["original_text"],
    "若乙方故意致伤，" + _risk()["original_text"],
    _risk()["original_text"][:-1] + "，但法律另有规定除外。",
])
def test_truncated_quote_cannot_hide_qualifiers_in_actual_contract(context):
    result = verify_support(_risk(), [_source()], mode="deterministic", contract_text=context)
    assert result.status == "unclear"
    assert result.reason_code == "ORIGINAL_CONTEXT_UNRESOLVED"


def test_audit_grounding_propagates_finite_rule_metadata_and_full_context(monkeypatch):
    from app.services.audit import auditor
    monkeypatch.setattr(auditor.settings, "EVIDENCE_VALIDATION_MODE", "deterministic")
    monkeypatch.setattr(auditor, "retrieve", lambda *_a, **_k: [_source(chunk_id=506)])
    original = _risk()["original_text"]
    for context, expected in ((original, "supported"), ("不得使用以下条款：" + original, "unclear"),
                              ("合同不采用“" + original + "”的表述。", "unclear")):
        result = auditor._ground_risks([_risk(confidence=85)], contract_text=context, dimensions=["risk"])[0]
        assert result["support_relation_status"] == expected
        assert result["decision_trace"]["evidence_validation"]["mode"] == "deterministic"
        if expected == "supported":
            assert result["decision_trace"]["evidence_validation"]["rule_id"] == "LEGAL-INJURY-WAIVER-001"
            assert result["evidence_ids"] == ["KC-506"]
            assert result["claim_status"] == "accepted"
        else:
            assert result["claim_status"] == "manual_review"
