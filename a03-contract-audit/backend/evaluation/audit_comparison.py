"""先过审查质量门槛，再比较可审计的成本、tokens 与延迟。"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import re
from typing import Any, Mapping, Sequence


QUALITY_THRESHOLDS: dict[str, tuple[str, float]] = {
    "high_risk_recall": ("min", 0.95),
    "false_success_rate": ("max", 0.0),
    "final_truncation_rate": ("max", 0.0),
    "quote_location_rate": ("min", 1.0),
    "invalid_legal_citation_rate": ("max", 0.0),
    "risk_recall": ("min", 0.90),
    "risk_precision": ("min", 0.85),
    "json_valid_rate": ("min", 1.0),
}
_COST_METRICS = (
    "mean_cost_per_success",
    "mean_prompt_tokens",
    "mean_completion_tokens",
    "p95_latency_ms",
)
_PRICING_FIELDS = ("currency", "pricing_source", "pricing_version")
_ABC_SCOPES = {
    "A": "baseline",
    "B": "output_budget_only",
    "C": "selective_cascade",
}
_FROZEN_CONTEXT_FIELDS = (
    "model_version",
    "prompt_version",
    "knowledge_base_version",
    "dataset_version",
    "temperature",
    "environment",
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_OPTIONAL_RATE_METRICS = ("manual_review_rate",)


@dataclass(frozen=True)
class ComparisonResult:
    status: str
    selected: str | None
    evaluation_basis: str | None
    contract_errors: list[str]
    quality_passed: list[str]
    rejected: dict[str, list[str]]
    ranking: list[str]
    thresholds: dict[str, dict[str, Any]]
    cost_inconclusive: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _finite_number(value: Any, name: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
    ):
        raise ValueError(f"{name} 必须是有限数值")
    return float(value)


def _validate_abc(candidates: Sequence[Mapping[str, Any]]) -> None:
    names = {str(candidate.get("candidate", "")) for candidate in candidates}
    if len(candidates) != 3 or names != {"A", "B", "C"}:
        raise ValueError("candidate_set")
    contexts: list[dict[str, Any]] = []
    for candidate in candidates:
        name = str(candidate["candidate"])
        experiment = candidate.get("experiment")
        if not isinstance(experiment, Mapping):
            raise ValueError(f"候选 {name} 缺少 experiment 元数据")
        if experiment.get("group") != name:
            raise ValueError(f"候选 {name} 的 experiment.group 不一致")
        if experiment.get("change_scope") != _ABC_SCOPES[name]:
            raise ValueError(f"候选 {name} 的 change_scope 不符合 A/B/C 定义")
        git_commit = experiment.get("git_commit")
        if not isinstance(git_commit, str) or not git_commit.strip():
            raise ValueError(f"候选 {name}.git_commit 必须是非空字符串")
        if name == "A" and git_commit.strip() != "94c8f9f":
            raise ValueError("基线 A 必须绑定代码提交 94c8f9f")
        budget = experiment.get("output_budget")
        if not isinstance(budget, int) or isinstance(budget, bool) or budget <= 0:
            raise ValueError(f"候选 {name}.output_budget 必须是正整数")
        if name == "A" and budget != 1600:
            raise ValueError("基线 A.output_budget 必须为 1600")
        if name == "B" and budget <= 1600:
            raise ValueError("候选 B.output_budget 必须大于基线 1600")
        context = experiment.get("frozen_context")
        if not isinstance(context, Mapping):
            raise ValueError(f"候选 {name} 缺少 frozen_context")
        missing = [field for field in _FROZEN_CONTEXT_FIELDS if field not in context]
        if missing:
            raise ValueError(f"候选 {name} frozen_context 缺少: {', '.join(missing)}")
        normalized_context = {
            field: context[field] for field in _FROZEN_CONTEXT_FIELDS
        }
        for field in _FROZEN_CONTEXT_FIELDS:
            if field == "temperature":
                normalized_context[field] = _finite_number(
                    context[field], f"候选 {name}.temperature"
                )
            elif not isinstance(context[field], str) or not context[field].strip():
                raise ValueError(f"候选 {name}.{field} 必须是非空字符串")
            else:
                normalized_context[field] = context[field].strip()
        contexts.append(normalized_context)
    if any(context != contexts[0] for context in contexts[1:]):
        raise ValueError("A/B/C 必须使用同一冻结上下文")


def _failed_gates(overall: Mapping[str, Any], candidate_name: str) -> list[str]:
    failed: list[str] = []
    for metric, (operator, threshold) in QUALITY_THRESHOLDS.items():
        value = overall.get(metric)
        if value is None:
            failed.append(metric)
            continue
        number = _finite_number(value, f"候选 {candidate_name}.{metric}")
        if number < 0 or number > 1:
            raise ValueError(f"候选 {candidate_name}.{metric} 必须介于 0 和 1")
        if (operator == "min" and number < threshold) or (
            operator == "max" and number > threshold
        ):
            failed.append(metric)
    return failed


def quality_gate_failures(overall: Mapping[str, Any]) -> list[str]:
    """返回未通过的固定质量门槛；None 视为未通过。"""
    if not isinstance(overall, Mapping):
        raise ValueError("overall 必须是对象")
    return _failed_gates(overall, "audit")


def _cost_key(candidate: Mapping[str, Any]) -> tuple[float, float, float, str]:
    overall = candidate["overall"]
    return (
        float(overall["mean_cost_per_success"]),
        float(overall["mean_prompt_tokens"]) + float(overall["mean_completion_tokens"]),
        float(overall["p95_latency_ms"]),
        str(candidate["candidate"]),
    )


def _has_complete_cost_evidence(candidate: Mapping[str, Any]) -> bool:
    name = str(candidate["candidate"])
    if candidate.get("cost_evidence_complete") is not True:
        return False
    overall = candidate["overall"]
    for metric in _COST_METRICS:
        value = overall.get(metric)
        if value is None:
            return False
        number = _finite_number(value, f"候选 {name}.{metric}")
        if number < 0:
            raise ValueError(f"候选 {name}.{metric} 不能为负数")
    metadata = candidate.get("cost_metadata")
    if not isinstance(metadata, Mapping):
        return False
    return all(isinstance(metadata.get(field), str) and metadata[field].strip() for field in _PRICING_FIELDS)


def _validate_known_metrics(candidate: Mapping[str, Any], name: str) -> None:
    overall = candidate["overall"]
    for metric in (*QUALITY_THRESHOLDS, *_OPTIONAL_RATE_METRICS):
        if metric not in overall or overall[metric] is None:
            continue
        number = _finite_number(overall[metric], f"候选 {name}.{metric}")
        if number < 0 or number > 1:
            raise ValueError(f"候选 {name}.{metric} 必须介于 0 和 1")
    for metric in _COST_METRICS:
        if overall.get(metric) is None:
            continue
        number = _finite_number(overall[metric], f"候选 {name}.{metric}")
        if number < 0:
            raise ValueError(f"候选 {name}.{metric} 不能为负数")
    if not isinstance(candidate.get("cost_evidence_complete"), bool):
        raise ValueError(f"候选 {name}.cost_evidence_complete 必须是布尔值")


def compare_audit_candidates(
    candidates: Sequence[Mapping[str, Any]],
) -> ComparisonResult:
    if not candidates:
        raise ValueError("候选方案不能为空")
    names: list[str] = []
    sample_counts: set[int] = set()
    gold_hashes: set[str] = set()
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, Mapping):
            raise ValueError(f"candidates[{index}] 必须是对象")
        name = candidate.get("candidate")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"candidates[{index}].candidate 必须是非空字符串")
        names.append(name.strip())
        sample_count = candidate.get("sample_count")
        if not isinstance(sample_count, int) or isinstance(sample_count, bool) or sample_count <= 0:
            raise ValueError(f"候选 {name}.sample_count 必须是正整数")
        sample_counts.add(sample_count)
        input_hashes = candidate.get("input_hashes")
        if not isinstance(input_hashes, Mapping):
            raise ValueError(f"候选 {name}.input_hashes 必须是对象")
        for field in ("gold_sha256", "predictions_sha256"):
            value = input_hashes.get(field)
            if not isinstance(value, str) or not _SHA256.fullmatch(value):
                raise ValueError(f"候选 {name}.input_hashes.{field} 不是有效 SHA-256")
        gold_hashes.add(str(input_hashes["gold_sha256"]))
        if not isinstance(candidate.get("overall"), Mapping):
            raise ValueError(f"候选 {name}.overall 必须是对象")
        _validate_known_metrics(candidate, name)
    if len(sample_counts) != 1:
        raise ValueError("所有候选的 sample_count 必须一致")
    if len(gold_hashes) != 1:
        raise ValueError("所有候选必须使用同一金标准数据集")

    bases = [candidate.get("evaluation_basis") for candidate in candidates]
    evaluation_basis = (
        str(bases[0])
        if bases
        and all(basis in {"synthetic", "human_gold"} for basis in bases)
        and len(set(bases)) == 1
        else None
    )
    contract_errors: list[str] = []
    if len(names) != len(set(names)):
        contract_errors.append("candidate_name_duplicate")
    if len(candidates) != 3 or set(names) != {"A", "B", "C"}:
        contract_errors.append("candidate_set")
    if evaluation_basis is None:
        contract_errors.append("evaluation_basis")
    if "candidate_set" not in contract_errors:
        try:
            _validate_abc(candidates)
        except ValueError as exc:
            contract_errors.append(f"experiment: {exc}")

    thresholds = {
        metric: {"operator": operator, "value": threshold}
        for metric, (operator, threshold) in QUALITY_THRESHOLDS.items()
    }
    if contract_errors:
        return ComparisonResult(
            status="failed",
            selected=None,
            evaluation_basis=evaluation_basis,
            contract_errors=contract_errors,
            quality_passed=[],
            rejected={name: ["experiment_contract"] for name in names},
            ranking=[],
            thresholds=thresholds,
            cost_inconclusive=[],
        )

    rejected: dict[str, list[str]] = {}
    passed: list[Mapping[str, Any]] = []
    for candidate in candidates:
        name = str(candidate["candidate"]).strip()
        failed = _failed_gates(candidate["overall"], name)
        if failed:
            rejected[name] = failed
        else:
            passed.append(candidate)

    if not passed:
        return ComparisonResult(
            status="failed",
            selected=None,
            evaluation_basis=evaluation_basis,
            contract_errors=[],
            quality_passed=[],
            rejected=rejected,
            ranking=[],
            thresholds=thresholds,
            cost_inconclusive=[],
        )

    cost_inconclusive = [
        str(candidate["candidate"])
        for candidate in passed
        if not _has_complete_cost_evidence(candidate)
    ]
    passed_names = [str(candidate["candidate"]) for candidate in passed]
    if cost_inconclusive:
        return ComparisonResult(
            status="quality_passed_cost_inconclusive",
            selected=None,
            evaluation_basis=evaluation_basis,
            contract_errors=[],
            quality_passed=passed_names,
            rejected=rejected,
            ranking=[],
            thresholds=thresholds,
            cost_inconclusive=cost_inconclusive,
        )

    pricing_bases = {
        tuple(str(candidate["cost_metadata"][field]) for field in _PRICING_FIELDS)
        for candidate in passed
    }
    if len(pricing_bases) != 1:
        raise ValueError("通过质量门槛的候选必须使用同一计价口径")

    ranked = sorted(passed, key=_cost_key)
    ranking = [str(candidate["candidate"]) for candidate in ranked]
    return ComparisonResult(
        status="passed",
        selected=ranking[0],
        evaluation_basis=evaluation_basis,
        contract_errors=[],
        quality_passed=passed_names,
        rejected=rejected,
        ranking=ranking,
        thresholds=thresholds,
        cost_inconclusive=[],
    )
