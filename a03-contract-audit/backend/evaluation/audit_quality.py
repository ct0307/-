"""合同审查风险质量、截断与成本的可审计评测。"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from evaluation.snapshot import read_jsonl_snapshot


_EVALUATION_BASES = frozenset({"synthetic", "human_gold"})
_SEVERITIES = frozenset({"low", "medium", "high"})
_STATUSES = frozenset({"done", "review_required", "audit_failed", "failed"})
_PRICING_FIELDS = ("currency", "pricing_source", "pricing_version")
_FROZEN_CONTEXT_FIELDS = (
    "model_version",
    "prompt_version",
    "knowledge_base_version",
    "dataset_version",
    "temperature",
    "environment",
)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _require_number(
    value: Any, name: str, *, integer: bool = False, minimum: float = 0
) -> int | float:
    valid_type = isinstance(value, int) and not isinstance(value, bool) if integer else _is_number(value)
    if not valid_type or (not integer and not math.isfinite(float(value))) or value < minimum:
        kind = "非负整数" if integer else "有限非负数"
        raise ValueError(f"{name} 必须是{kind}")
    return value


def _require_nonempty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} 必须是非空字符串")
    return value.strip()


def _require_list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{name} 必须是数组")
    return value


def _ratio(numerator: int | float, denominator: int | float) -> float | None:
    return numerator / denominator if denominator else None


def _mean(total: int | float, count: int) -> float | None:
    return total / count if count else None


def _percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    fraction = position - lower
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction)


def _canonical_sha256(records: Sequence[Mapping[str, Any]]) -> str:
    value = json.dumps(
        records, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _validate_gold(
    records: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Mapping[str, Any]], dict[str, str], str]:
    cases: dict[str, Mapping[str, Any]] = {}
    risk_to_case: dict[str, str] = {}
    bases: set[str] = set()
    for case_index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise ValueError(f"gold[{case_index}] 必须是 JSON 对象")
        case_id = _require_nonempty_string(record.get("case_id"), f"gold[{case_index}].case_id")
        if case_id in cases:
            raise ValueError(f"金标准 case_id 重复: {case_id}")
        basis = _require_nonempty_string(
            record.get("evaluation_basis"), f"gold[{case_index}].evaluation_basis"
        )
        if basis not in _EVALUATION_BASES:
            raise ValueError("evaluation_basis 只能是 synthetic 或 human_gold")
        if basis == "human_gold":
            reviewers = _require_list(record.get("reviewers"), f"gold[{case_index}].reviewers")
            normalized_reviewers = [
                _require_nonempty_string(item, f"gold[{case_index}].reviewers")
                for item in reviewers
            ]
            if len(set(normalized_reviewers)) < 2:
                raise ValueError(f"gold[{case_index}].reviewers 必须包含两名独立复核人")
            review_status = _require_nonempty_string(
                record.get("review_status"), f"gold[{case_index}].review_status"
            )
            if review_status not in {"agreed", "adjudicated"}:
                raise ValueError(
                    f"gold[{case_index}].review_status 必须是 agreed 或 adjudicated"
                )
            if review_status == "adjudicated":
                adjudicator = _require_nonempty_string(
                    record.get("adjudicator"), f"gold[{case_index}].adjudicator"
                )
                if adjudicator in set(normalized_reviewers):
                    raise ValueError(f"gold[{case_index}].adjudicator 必须是独立第三人")
        bases.add(basis)
        risks = _require_list(record.get("risks"), f"gold[{case_index}].risks")
        local_ids: set[str] = set()
        for risk_index, risk in enumerate(risks):
            prefix = f"gold[{case_index}].risks[{risk_index}]"
            if not isinstance(risk, Mapping):
                raise ValueError(f"{prefix} 必须是对象")
            gold_id = _require_nonempty_string(risk.get("gold_risk_id"), f"{prefix}.gold_risk_id")
            if gold_id in local_ids or gold_id in risk_to_case:
                raise ValueError(f"gold_risk_id 重复: {gold_id}")
            local_ids.add(gold_id)
            severity = _require_nonempty_string(risk.get("severity"), f"{prefix}.severity")
            if severity not in _SEVERITIES:
                raise ValueError(f"{prefix}.severity 必须是 low、medium 或 high")
            _require_nonempty_string(risk.get("category"), f"{prefix}.category")
            location = risk.get("location")
            if not isinstance(location, Mapping):
                raise ValueError(f"{prefix}.location 必须是对象")
            _require_nonempty_string(location.get("clause_id"), f"{prefix}.location.clause_id")
            start = _require_number(
                location.get("start"), f"{prefix}.location.start", integer=True
            )
            end = _require_number(location.get("end"), f"{prefix}.location.end", integer=True)
            if end <= start:
                raise ValueError(f"{prefix}.location.end 必须大于 start")
            evidence_ids = _require_list(risk.get("evidence_ids"), f"{prefix}.evidence_ids")
            if not evidence_ids:
                raise ValueError(f"{prefix}.evidence_ids 不能为空")
            normalized_evidence = [
                _require_nonempty_string(item, f"{prefix}.evidence_ids") for item in evidence_ids
            ]
            if len(normalized_evidence) != len(set(normalized_evidence)):
                raise ValueError(f"{prefix}.evidence_ids 不能重复")
            risk_to_case[gold_id] = case_id
        cases[case_id] = record
    if len(bases) != 1:
        raise ValueError("同一评测不能混用 synthetic 与 human_gold 口径")
    return cases, risk_to_case, next(iter(bases))


def _validate_prediction_records(
    records: Sequence[Mapping[str, Any]], gold_cases: Mapping[str, Mapping[str, Any]]
) -> dict[str, Mapping[str, Any]]:
    predictions: dict[str, Mapping[str, Any]] = {}
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise ValueError(f"predictions[{index}] 必须是 JSON 对象")
        case_id = _require_nonempty_string(
            record.get("case_id"), f"predictions[{index}].case_id"
        )
        if case_id in predictions:
            raise ValueError(f"预测 case_id 重复: {case_id}")
        if case_id not in gold_cases:
            raise ValueError(f"预测集包含未知 case_id: {case_id}")
        predictions[case_id] = record
    return predictions


def _missing_prediction(case_id: str) -> Mapping[str, Any]:
    return {
        "case_id": case_id,
        "status": "audit_failed",
        "risks": [],
        "finish_reasons": [],
        "coverage": {"completed": 0, "total": 1},
        "calls": [],
    }


def _safe_experiment(value: Mapping[str, Any], name: str) -> dict[str, Any]:
    result = {
        field: _require_nonempty_string(value.get(field), f"{name}.{field}")
        for field in ("group", "git_commit", "change_scope")
    }
    result["output_budget"] = _require_number(
        value.get("output_budget"), f"{name}.output_budget", integer=True, minimum=1
    )
    context = value.get("frozen_context")
    if not isinstance(context, Mapping):
        raise ValueError(f"{name}.frozen_context 必须是对象")
    missing = [field for field in _FROZEN_CONTEXT_FIELDS if field not in context]
    if missing:
        raise ValueError(f"{name}.frozen_context 缺少: {', '.join(missing)}")
    safe_context = {
        field: _require_nonempty_string(context[field], f"{name}.frozen_context.{field}")
        for field in _FROZEN_CONTEXT_FIELDS
        if field != "temperature"
    }
    safe_context["temperature"] = _require_number(
        context["temperature"], f"{name}.frozen_context.temperature"
    )
    result["frozen_context"] = safe_context
    return result


def summarize_audit_cases(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """仅从脱敏 case 计数重算全部质量、调用与成本指标。"""
    if not cases:
        raise ValueError("audit case 不能为空")

    seen_case_ids: set[str] = set()
    gold_count = 0
    high_gold_count = 0
    predicted_count = 0
    matched_count = 0
    matched_high_count = 0
    located_count = 0
    invalid_citation_count = 0
    total_calls = 0
    valid_json_calls = 0
    prompt_tokens = 0
    completion_tokens = 0
    total_cost = 0.0
    done_count = 0
    false_done = 0
    truncated_contracts = 0
    review_required = 0
    successful_contracts = 0
    contract_latencies: list[float] = []
    pricing_values: list[tuple[str, str, str]] = []
    cost_evidence_complete = True
    experiments: list[dict[str, Any]] = []

    for index, case in enumerate(cases):
        if not isinstance(case, Mapping):
            raise ValueError(f"audit case[{index}] 必须是对象")
        prefix = f"audit case[{index}]"
        allowed_fields = {
            "event",
            "case_id",
            "status",
            "gold_risk_count",
            "high_gold_risk_count",
            "predicted_risk_count",
            "matched_risk_count",
            "matched_high_risk_count",
            "quote_located_count",
            "invalid_legal_citation_count",
            "truncated",
            "coverage",
            "call_count",
            "valid_json_call_count",
            "prompt_tokens",
            "completion_tokens",
            "latency_ms",
            "cost",
            "cost_evidence_complete",
            "cost_metadata",
            "successful",
            "experiment",
        }
        unknown_fields = set(case) - allowed_fields
        if unknown_fields:
            raise ValueError(f"{prefix} 包含未授权字段: {sorted(unknown_fields)}")
        if "event" in case and case.get("event") != "case":
            raise ValueError(f"{prefix}.event 必须是 case")
        case_id = _require_nonempty_string(case.get("case_id"), f"{prefix}.case_id")
        if case_id in seen_case_ids:
            raise ValueError(f"audit case_id 重复: {case_id}")
        seen_case_ids.add(case_id)
        status = _require_nonempty_string(case.get("status"), f"{prefix}.status")
        if status not in _STATUSES:
            raise ValueError(f"{prefix}.status 不受支持: {status}")

        counts = {
            field: int(_require_number(case.get(field), f"{prefix}.{field}", integer=True))
            for field in (
                "gold_risk_count",
                "high_gold_risk_count",
                "predicted_risk_count",
                "matched_risk_count",
                "matched_high_risk_count",
                "quote_located_count",
                "invalid_legal_citation_count",
                "call_count",
                "valid_json_call_count",
                "prompt_tokens",
                "completion_tokens",
            )
        }
        if counts["high_gold_risk_count"] > counts["gold_risk_count"]:
            raise ValueError(f"{prefix}.high_gold_risk_count 超过 gold_risk_count")
        if counts["matched_risk_count"] > min(
            counts["gold_risk_count"], counts["predicted_risk_count"]
        ):
            raise ValueError(f"{prefix}.matched_risk_count 超出计数边界")
        if counts["matched_high_risk_count"] > min(
            counts["high_gold_risk_count"], counts["matched_risk_count"]
        ):
            raise ValueError(f"{prefix}.matched_high_risk_count 超出计数边界")
        if counts["quote_located_count"] > counts["predicted_risk_count"]:
            raise ValueError(f"{prefix}.quote_located_count 超过 predicted_risk_count")
        if counts["invalid_legal_citation_count"] > counts["predicted_risk_count"]:
            raise ValueError(
                f"{prefix}.invalid_legal_citation_count 超过 predicted_risk_count"
            )
        if counts["valid_json_call_count"] > counts["call_count"]:
            raise ValueError(f"{prefix}.valid_json_call_count 超过 call_count")

        truncated = case.get("truncated")
        successful = case.get("successful")
        case_cost_complete = case.get("cost_evidence_complete")
        if not isinstance(truncated, bool):
            raise ValueError(f"{prefix}.truncated 必须是布尔值")
        if not isinstance(successful, bool):
            raise ValueError(f"{prefix}.successful 必须是布尔值")
        if not isinstance(case_cost_complete, bool):
            raise ValueError(f"{prefix}.cost_evidence_complete 必须是布尔值")
        coverage = case.get("coverage")
        if not isinstance(coverage, Mapping):
            raise ValueError(f"{prefix}.coverage 必须是对象")
        completed = int(
            _require_number(
                coverage.get("completed"), f"{prefix}.coverage.completed", integer=True
            )
        )
        total = int(
            _require_number(
                coverage.get("total"),
                f"{prefix}.coverage.total",
                integer=True,
                minimum=1,
            )
        )
        if completed > total:
            raise ValueError(f"{prefix}.coverage.completed 不能大于 total")
        expected_success = status == "done" and not truncated and completed == total
        if successful != expected_success:
            raise ValueError(f"{prefix}.successful 与状态、截断或覆盖率矛盾")
        if status in {"audit_failed", "failed"}:
            failed_risk_fields = (
                "predicted_risk_count",
                "matched_risk_count",
                "matched_high_risk_count",
                "quote_located_count",
                "invalid_legal_citation_count",
            )
            nonzero_fields = [field for field in failed_risk_fields if counts[field] != 0]
            if nonzero_fields:
                raise ValueError(
                    f"{prefix} 失败状态的风险与匹配计数必须为 0: "
                    f"{', '.join(nonzero_fields)}"
                )

        latency = float(_require_number(case.get("latency_ms"), f"{prefix}.latency_ms"))
        cost = float(_require_number(case.get("cost"), f"{prefix}.cost"))
        metadata = case.get("cost_metadata")
        normalized_metadata: tuple[str, str, str] | None = None
        if metadata is not None:
            if not isinstance(metadata, Mapping):
                raise ValueError(f"{prefix}.cost_metadata 必须是对象或 null")
            normalized_metadata = tuple(
                _require_nonempty_string(metadata.get(field), f"{prefix}.cost_metadata.{field}")
                for field in _PRICING_FIELDS
            )
            pricing_values.append(normalized_metadata)
        if case_cost_complete and (
            counts["call_count"] == 0 or normalized_metadata is None
        ):
            raise ValueError(f"{prefix} 成本证据完整性与调用或计价元数据矛盾")
        cost_evidence_complete = cost_evidence_complete and case_cost_complete

        experiment = case.get("experiment")
        if experiment is not None:
            if not isinstance(experiment, Mapping):
                raise ValueError(f"{prefix}.experiment 必须是对象")
            experiments.append(_safe_experiment(experiment, f"{prefix}.experiment"))

        gold_count += counts["gold_risk_count"]
        high_gold_count += counts["high_gold_risk_count"]
        predicted_count += counts["predicted_risk_count"]
        matched_count += counts["matched_risk_count"]
        matched_high_count += counts["matched_high_risk_count"]
        located_count += counts["quote_located_count"]
        invalid_citation_count += counts["invalid_legal_citation_count"]
        total_calls += counts["call_count"]
        valid_json_calls += counts["valid_json_call_count"]
        prompt_tokens += counts["prompt_tokens"]
        completion_tokens += counts["completion_tokens"]
        total_cost += cost
        done_count += int(status == "done")
        false_done += int(status == "done" and not expected_success)
        truncated_contracts += int(truncated)
        review_required += int(status == "review_required")
        successful_contracts += int(successful)
        contract_latencies.append(latency)

    unique_pricing = set(pricing_values)
    if len(unique_pricing) > 1:
        raise ValueError("评测中的 currency、pricing_source 和 pricing_version 必须一致")
    if len(pricing_values) != len(cases):
        cost_evidence_complete = False
    if experiments and len(experiments) != len(cases):
        raise ValueError("所有预测合同必须使用同一 experiment 元数据")
    experiment: dict[str, Any] | None = None
    if experiments:
        canonical = {
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            for value in experiments
        }
        if len(canonical) != 1:
            raise ValueError("所有预测合同的 experiment 元数据必须一致")
        experiment = experiments[0]

    result: dict[str, Any] = {
        "overall": {
            "high_risk_recall": _ratio(matched_high_count, high_gold_count),
            "risk_recall": _ratio(matched_count, gold_count),
            "risk_precision": _ratio(matched_count, predicted_count),
            "quote_location_rate": _ratio(located_count, predicted_count),
            "invalid_legal_citation_rate": _ratio(
                invalid_citation_count, predicted_count
            ),
            "json_valid_rate": _ratio(valid_json_calls, total_calls),
            "final_truncation_rate": _ratio(truncated_contracts, len(cases)),
            "false_success_rate": _ratio(false_done, done_count),
            "manual_review_rate": _ratio(review_required, len(cases)),
            "mean_prompt_tokens": _mean(prompt_tokens, len(cases)),
            "mean_completion_tokens": _mean(completion_tokens, len(cases)),
            "mean_cost_per_success": (
                _mean(total_cost, successful_contracts)
                if cost_evidence_complete
                else None
            ),
            "p95_latency_ms": _percentile(contract_latencies, 0.95),
        },
        "cost_evidence_complete": cost_evidence_complete,
        "cost_metadata": (
            dict(zip(_PRICING_FIELDS, next(iter(unique_pricing))))
            if cost_evidence_complete and unique_pricing
            else None
        ),
    }
    if experiment is not None:
        result["experiment"] = experiment
    return result


def evaluate_audit_dataset(
    *,
    gold: Sequence[Mapping[str, Any]],
    predictions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """仅根据显式人工匹配计算指标，不做语义推断。"""
    if not gold:
        raise ValueError("金标准不能为空")
    gold_cases, gold_risk_to_case, evaluation_basis = _validate_gold(gold)
    prediction_cases = _validate_prediction_records(predictions, gold_cases)

    high_gold_ids = {
        str(risk["gold_risk_id"])
        for record in gold_cases.values()
        for risk in record["risks"]
        if risk["severity"] == "high"
    }
    matched_ids: set[str] = set()
    cases: list[dict[str, Any]] = []

    for case_id, gold_case in gold_cases.items():
        prediction = prediction_cases.get(case_id, _missing_prediction(case_id))
        status = _require_nonempty_string(prediction.get("status"), f"{case_id}.status")
        if status not in _STATUSES:
            raise ValueError(f"{case_id}.status 不受支持: {status}")
        risks = _require_list(prediction.get("risks"), f"{case_id}.risks")
        if status in {"audit_failed", "failed"} and risks:
            raise ValueError(f"{case_id} 失败状态不得携带风险")
        candidate_ids: set[str] = set()
        case_matched = 0
        case_matched_high = 0
        case_located = 0
        case_invalid_citations = 0
        for risk_index, risk in enumerate(risks):
            prefix = f"{case_id}.risks[{risk_index}]"
            if not isinstance(risk, Mapping):
                raise ValueError(f"{prefix} 必须是对象")
            candidate_id = _require_nonempty_string(
                risk.get("candidate_id"), f"{prefix}.candidate_id"
            )
            if candidate_id in candidate_ids:
                raise ValueError(f"{case_id} candidate_id 重复: {candidate_id}")
            candidate_ids.add(candidate_id)
            if "matched_gold_id" not in risk:
                raise ValueError(f"{prefix}.matched_gold_id 必须由人工标注为 ID 或 null")
            matched_gold_id = risk["matched_gold_id"]
            if matched_gold_id is not None:
                matched_gold_id = _require_nonempty_string(
                    matched_gold_id, f"{prefix}.matched_gold_id"
                )
                owner = gold_risk_to_case.get(matched_gold_id)
                if owner is None:
                    raise ValueError(f"预测匹配未知 gold_risk_id: {matched_gold_id}")
                if owner != case_id:
                    raise ValueError(f"{matched_gold_id} 不属于合同 {case_id}")
                if matched_gold_id in matched_ids:
                    raise ValueError(f"gold_risk_id 重复匹配: {matched_gold_id}")
                matched_ids.add(matched_gold_id)
                case_matched += 1
                case_matched_high += int(matched_gold_id in high_gold_ids)
            quote_located = risk.get("quote_located")
            invalid_citation = risk.get("invalid_legal_citation")
            if not isinstance(quote_located, bool):
                raise ValueError(f"{prefix}.quote_located 必须是布尔值")
            if not isinstance(invalid_citation, bool):
                raise ValueError(f"{prefix}.invalid_legal_citation 必须是布尔值")
            case_located += int(quote_located)
            case_invalid_citations += int(invalid_citation)

        finish_reasons = _require_list(
            prediction.get("finish_reasons"), f"{case_id}.finish_reasons"
        )
        if any(not isinstance(reason, str) for reason in finish_reasons):
            raise ValueError(f"{case_id}.finish_reasons 必须是字符串数组")
        truncated = any(reason.strip().lower() == "length" for reason in finish_reasons)
        coverage = prediction.get("coverage")
        if not isinstance(coverage, Mapping):
            raise ValueError(f"{case_id}.coverage 必须是对象")
        completed = _require_number(
            coverage.get("completed"), f"{case_id}.coverage.completed", integer=True
        )
        total = _require_number(
            coverage.get("total"), f"{case_id}.coverage.total", integer=True, minimum=1
        )
        if completed > total:
            raise ValueError(f"{case_id}.coverage.completed 不能大于 total")
        complete_coverage = completed == total

        calls = _require_list(prediction.get("calls"), f"{case_id}.calls")
        case_prompt_tokens = 0
        case_completion_tokens = 0
        case_cost = 0.0
        case_latency = 0.0
        case_valid_json_calls = 0
        calls_have_cost = bool(calls)
        for call_index, call in enumerate(calls):
            prefix = f"{case_id}.calls[{call_index}]"
            if not isinstance(call, Mapping):
                raise ValueError(f"{prefix} 必须是对象")
            json_valid = call.get("json_valid")
            if not isinstance(json_valid, bool):
                raise ValueError(f"{prefix}.json_valid 必须是布尔值")
            current_prompt = _require_number(
                call.get("prompt_tokens"), f"{prefix}.prompt_tokens", integer=True
            )
            current_completion = _require_number(
                call.get("completion_tokens"), f"{prefix}.completion_tokens", integer=True
            )
            current_latency = _require_number(call.get("latency_ms"), f"{prefix}.latency_ms")
            if "cost" not in call:
                calls_have_cost = False
                current_cost = 0.0
            else:
                current_cost = float(_require_number(call.get("cost"), f"{prefix}.cost"))
            case_valid_json_calls += int(json_valid)
            case_prompt_tokens += int(current_prompt)
            case_completion_tokens += int(current_completion)
            case_latency += float(current_latency)
            case_cost += current_cost

        metadata_values: list[str] = []
        for field in _PRICING_FIELDS:
            value = prediction.get(field)
            if not isinstance(value, str) or not value.strip():
                metadata_values.append("")
            else:
                metadata_values.append(value.strip())
        case_cost_metadata = (
            dict(zip(_PRICING_FIELDS, metadata_values)) if all(metadata_values) else None
        )
        case_cost_evidence_complete = calls_have_cost and case_cost_metadata is not None
        case_experiment: dict[str, Any] | None = None
        if "experiment" in prediction:
            if not isinstance(prediction["experiment"], Mapping):
                raise ValueError(f"{case_id}.experiment 必须是对象")
            case_experiment = _safe_experiment(
                prediction["experiment"], f"{case_id}.experiment"
            )

        is_false_done = status == "done" and (truncated or not complete_coverage)
        is_success = status == "done" and not is_false_done
        case_summary: dict[str, Any] = {
            "case_id": case_id,
            "status": status,
            "gold_risk_count": len(gold_case["risks"]),
            "high_gold_risk_count": sum(
                int(risk["severity"] == "high") for risk in gold_case["risks"]
            ),
            "predicted_risk_count": len(risks),
            "matched_risk_count": case_matched,
            "matched_high_risk_count": case_matched_high,
            "quote_located_count": case_located,
            "invalid_legal_citation_count": case_invalid_citations,
            "truncated": truncated,
            "coverage": {"completed": completed, "total": total},
            "call_count": len(calls),
            "valid_json_call_count": case_valid_json_calls,
            "prompt_tokens": case_prompt_tokens,
            "completion_tokens": case_completion_tokens,
            "latency_ms": case_latency,
            "cost": case_cost,
            "cost_evidence_complete": case_cost_evidence_complete,
            "cost_metadata": case_cost_metadata,
            "successful": is_success,
        }
        if case_experiment is not None:
            case_summary["experiment"] = case_experiment
        cases.append(case_summary)

    derived = summarize_audit_cases(cases)
    result: dict[str, Any] = {
        "sample_count": len(gold_cases),
        "evaluation_basis": evaluation_basis,
        "input_hashes": {
            "gold_sha256": _canonical_sha256(gold),
            "predictions_sha256": _canonical_sha256(predictions),
        },
        "overall": derived["overall"],
        "cases": cases,
        "cost_evidence_complete": derived["cost_evidence_complete"],
        "cost_metadata": derived["cost_metadata"],
    }
    if "experiment" in derived:
        result["experiment"] = derived["experiment"]
    return result


def evaluate_audit_files(gold_path: Path, predictions_path: Path) -> dict[str, Any]:
    """读取 JSONL 并将哈希绑定到文件的精确字节。"""
    gold_path = Path(gold_path)
    predictions_path = Path(predictions_path)
    gold, gold_sha256 = read_jsonl_snapshot(gold_path, "金标准")
    predictions, predictions_sha256 = read_jsonl_snapshot(predictions_path, "预测")
    report = evaluate_audit_dataset(
        gold=gold,
        predictions=predictions,
    )
    report["input_hashes"] = {
        "gold_sha256": gold_sha256,
        "predictions_sha256": predictions_sha256,
    }
    return report
