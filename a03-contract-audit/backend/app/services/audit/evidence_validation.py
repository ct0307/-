"""风险结论与检索依据之间的保守支持关系校验。"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


SUPPORT_VALIDATOR_VERSION = "rules-v2"
SUPPORT_V3_VERSION = "support-v4"
DETERMINISTIC_SUPPORT_VERSION = "support-deterministic-v1"
EVIDENCE_VALIDATION_MODES = {"manual_only", "deterministic"}

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
    failed_stage: str = "none"
    # 旧版校验结果没有稳定的原因码；留空后由查询执行器按 status 回退。
    reason_code: str = ""
    evidence_relations: tuple[dict, ...] = ()
    mode: str = "manual_only"
    rule_id: str = ""
    rule_version: str = ""


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


def verify_support(
    risk: dict,
    sources: list[dict] | tuple[dict, ...],
    *,
    semantic_verifier=None,
    mode: str | None = None,
    contract_text: str | None = None,
) -> SupportValidation:
    """按显式模式核验证据，无法确定时保持人工复核。"""
    from dataclasses import replace

    effective_mode = mode or ("manual_only" if semantic_verifier is None else "semantic")
    if effective_mode not in EVIDENCE_VALIDATION_MODES and effective_mode != "semantic":
        raise ValueError(f"unsupported evidence validation mode: {effective_mode}")
    if not sources:
        return _verify_single(risk, [], semantic_verifier=semantic_verifier, mode=effective_mode, contract_text=contract_text)
    outcomes = [
        _verify_single(risk, [source], semantic_verifier=semantic_verifier, mode=effective_mode, contract_text=contract_text)
        for source in sources
    ]
    relations = tuple({
        "source": dict(source),
        "relation": "supporting" if result.status == "supported" else
                    "contradicting" if result.status == "contradicted" else
                    "rejected" if result.failed_stage in {"authority", "applicability"} else "contextual",
        "status": result.status,
        "reason_code": result.reason_code,
        "reason": result.reason,
        "validator_version": result.version,
        "mode": result.mode,
        "failed_stage": result.failed_stage,
        "rule_id": result.rule_id,
        "rule_version": result.rule_version,
    } for source, result in zip(sources, outcomes))
    statuses = {result.status for result in outcomes}
    if {"supported", "contradicted"} <= statuses:
        result = _v3("unclear", "semantic_relation", "CONFLICTING_EVIDENCE", "支持与反驳依据并存，等待人工裁决", mode=effective_mode)
    elif "contradicted" in statuses:
        result = next(result for result in outcomes if result.status == "contradicted")
    elif "supported" in statuses:
        result = next(result for result in outcomes if result.status == "supported")
    else:
        result = outcomes[0]
    return replace(result, evidence_relations=relations)


def _verify_single(
    risk: dict,
    sources: list[dict],
    *,
    semantic_verifier=None,
    mode: str = "manual_only",
    contract_text: str | None = None,
) -> SupportValidation:
    """单个候选来源的分阶段核验。"""
    original = str(risk.get("original_text") or "").strip()
    if risk.get("original_text_verified") is not True or not original:
        return _v3("unclear", "original", "ORIGINAL_TEXT_UNRESOLVED", "原文未完成精确定位", mode=mode)

    usable = [
        source for source in sources
        if source.get("reliable") is True
        and str(source.get("source") or "").strip()
        and str(source.get("content") or "").strip()
    ]
    if not usable:
        return _v3("unclear", "authority", "SOURCE_AUTHORITY_UNRESOLVED", "没有可用的已核验权威来源", mode=mode)

    applicability = {str(source.get("applicability_status") or "unknown") for source in usable}
    if applicability != {"applicable"}:
        return _v3("unclear", "applicability", "SOURCE_NOT_APPLICABLE", "来源适用性未确认或已失效", mode=mode)

    if mode == "deterministic":
        return _verify_deterministic(risk, usable[0], contract_text=contract_text)

    risk_fragments = set().union(*(
        _meaningful_fragments(str(risk.get(field, "")))
        for field in ("category", "original_text", "risk_reason")
    ))
    source_text = " ".join(str(source["content"]) for source in usable).lower()
    matched = {fragment for fragment in risk_fragments if fragment in source_text}
    if len(matched) < 2:
        return _v3("unclear", "facts", "FACTS_NOT_ALIGNED", "来源内容与风险事实缺少足够的一致性", mode=mode)

    if mode == "manual_only" or semantic_verifier is None:
        return _v3("unclear", "semantic_relation", "SEMANTIC_VERIFIER_UNAVAILABLE", "未启用经过验证的语义判断器，需人工核验", mode=mode)
    try:
        relation = semantic_verifier(risk, usable)
    except Exception:
        return _v3("unclear", "semantic_relation", "SEMANTIC_VERIFIER_FAILED", "语义验证不可用，需人工核验", mode=mode)
    if relation == "contradicted":
        return _v3("contradicted", "semantic_relation", "EVIDENCE_CONTRADICTS_CLAIM", "权威来源与风险结论存在语义矛盾", mode=mode)
    if relation != "supported":
        return _v3("unclear", "semantic_relation", "SEMANTIC_RELATION_UNRESOLVED", "语义关系验证未得到明确支持", mode=mode)
    return _v3("supported", "none", "EVIDENCE_SUPPORTS_CLAIM", "本条证据已通过来源、适用性、事实和语义验证", mode=mode)


def _v3(status: str, failed_stage: str, reason_code: str, reason: str, *, mode: str = "manual_only") -> SupportValidation:
    return SupportValidation(
        status=status,
        reason=reason,
        failed_stage=failed_stage,
        reason_code=reason_code,
        mode=mode,
        version=DETERMINISTIC_SUPPORT_VERSION if mode == "deterministic" else SUPPORT_V3_VERSION,
    )


def _verify_deterministic(risk: dict, source: dict, *, contract_text: str | None) -> SupportValidation:
    """仅验证已定义的绝对免责句式与民法典506条，其他情形交人工。"""
    from dataclasses import replace
    from app.services.audit.rules.executor import execute_rule
    from app.services.audit.rules.registry import load_registry

    mode = "deterministic"
    # 完整句式限制否定、引用、例外和附条件场景；规则命中本身不能证明法律结论。
    original = unicodedata.normalize("NFKC", str(risk.get("original_text") or ""))
    original = re.sub(r"\s+", "", original)
    waiver = re.fullmatch(
        r"(?P<liable>甲方|乙方)不承担(?P<injured>甲方|乙方|对方)在"
        r"(?:提供劳务|提供服务|履行合同|工作|履约)过程中的"
        r"(?:工伤(?:[、,或及]意外伤害)?|意外伤害)等?(?:任何|全部)(?:赔偿)?责任[。.!！]?",
        original,
    )
    risk_text = " ".join(str(risk.get(field) or "") for field in ("category", "risk_reason"))
    if (risk.get("category") != "人身损害免责责任风险" or waiver is None
            or waiver.group("liable") == waiver.group("injured")
            or any(marker in risk_text for marker in _ABSENCE_MARKERS)):
        return _v3("unclear", "facts", "DETERMINISTIC_RULE_NOT_PROVEN", "未满足有限规则的完整事实条件，需人工核验", mode=mode)
    # 从真实全文回读完整句子，防止模型仅截取免责句而遗漏删除说明、条件或例外。
    context = unicodedata.normalize("NFKC", contract_text or "")
    context = re.sub(r"\s+", "", context)
    quote = original.rstrip("。.!！")
    sentences = re.split(r"[。.!！?？;；]", context)
    if (not context or quote not in sentences
            or re.search(r'若|如果|除非|例外|但|除外|示例|删除|不适用|不生效|不得|不应|无效|条件|另行约定|[“”「」"]', context)):
        return _v3("unclear", "original", "ORIGINAL_CONTEXT_UNRESOLVED", "全文上下文无法排除条件、引用或例外，需人工核验", mode=mode)
    try:
        rule = next(rule for rule in load_registry().rules
                    if rule.rule_id == "LEGAL-INJURY-WAIVER-001" and rule.version == "1.0.0"
                    and rule.handler == "absolute_injury_waiver")
        outcome = execute_rule(rule, {"contract_text": risk["original_text"]})
    except Exception:
        return _v3("unclear", "facts", "DETERMINISTIC_VERIFIER_UNAVAILABLE", "版本化规则不可用，需人工核验", mode=mode)
    if outcome.status != "hit" or not outcome.facts.get("quote"):
        return _v3("unclear", "facts", "DETERMINISTIC_VERIFIER_UNAVAILABLE", "版本化规则未确认原文，需人工核验", mode=mode)
    law_name = re.sub(r"[\s《》]", "", str(source.get("source") or ""))
    article = str(source.get("article_number") or "").strip()
    law_text = re.sub(r"[\s，,。.;；：:（）()、]", "", unicodedata.normalize("NFKC", str(source.get("content") or "")))
    if (law_name not in {"中华人民共和国民法典", "民法典"}
            or article not in {"第五百零六条", "第506条", "506"}
            or not re.fullmatch(r"(?:第五百零六条|第506条)?合同中的下列免责条款无效(?:一|1)造成对方人身损害的(?:二|2)因故意或者重大过失造成对方财产损失的", law_text)):
        return _v3("unclear", "semantic_relation", "DETERMINISTIC_SOURCE_NOT_PROVEN", "来源未满足民法典506条的有限验证条件，需人工核验", mode=mode)
    result = _v3("supported", "none", "EVIDENCE_SUPPORTS_CLAIM", "已核验绝对免责完整句式与民法典506条；仅支持该限定风险", mode=mode)
    return replace(result, rule_id=rule.rule_id, rule_version=rule.version)
