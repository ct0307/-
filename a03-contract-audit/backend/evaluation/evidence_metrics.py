"""风险依据支持关系的金标评测。"""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

from evaluation.elements import validate_gold_record


SUPPORT_STATUSES = ("supported", "unclear", "contradicted")


def validate_evidence_gold_record(record: Mapping[str, Any]) -> None:
    """校验一条带风险证据金标的合同记录。"""
    validate_gold_record(record)
    evidence = record.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("金标准 evidence 必须是非空数组")
    seen: set[str] = set()
    for index, item in enumerate(evidence):
        if not isinstance(item, Mapping):
            raise ValueError(f"evidence[{index}] 必须是对象")
        risk_key = str(item.get("risk_key", "")).strip()
        status = str(item.get("support_relation_status", "")).strip()
        if not risk_key:
            raise ValueError(f"evidence[{index}] 缺少 risk_key")
        if risk_key in seen:
            raise ValueError(f"evidence risk_key 重复: {risk_key}")
        if status not in SUPPORT_STATUSES:
            raise ValueError(
                f"evidence[{index}] support_relation_status 必须为 {SUPPORT_STATUSES}"
            )
        seen.add(risk_key)


def evaluate_evidence_dataset(
    gold_records: Sequence[Mapping[str, Any]],
    predictions: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """评测风险级支持关系预测，缺失预测按错误计入。"""
    if not gold_records:
        raise ValueError("证据金标准不能为空")
    for record in gold_records:
        validate_evidence_gold_record(record)

    gold_by_case = {str(record["case_id"]): record for record in gold_records}
    unknown_ids = sorted(set(predictions) - set(gold_by_case))
    if unknown_ids:
        raise ValueError(f"未知预测 case_id: {', '.join(unknown_ids)}")

    case_reports: list[dict[str, Any]] = []
    totals = Counter()
    total_count = correct_count = missing_count = 0
    for case_id, record in gold_by_case.items():
        gold_items = {
            str(item["risk_key"]): str(item["support_relation_status"])
            for item in record["evidence"]
        }
        prediction_items = _prediction_items(predictions.get(case_id, {}))
        unknown_keys = sorted(set(prediction_items) - set(gold_items))
        if unknown_keys:
            raise ValueError(f"未知 risk_key: {', '.join(unknown_keys)}")

        pairs: list[tuple[str, str | None]] = [
            (expected, prediction_items.get(key))
            for key, expected in gold_items.items()
        ]
        case_correct = sum(actual == expected for expected, actual in pairs)
        case_missing = sum(actual is None for _, actual in pairs)
        metrics = _classification_metrics(pairs)
        case_reports.append({
            "case_id": case_id,
            "contract_type": record["contract_type"],
            "document_kind": record["document_kind"],
            "risk_count": len(pairs),
            "correct_count": case_correct,
            "missing_prediction_count": case_missing,
            "metrics": metrics,
        })
        correct_count += case_correct
        missing_count += case_missing
        total_count += len(pairs)
        for expected, actual in pairs:
            totals[(expected, actual)] += 1

    overall_metrics = _classification_metrics(
        [
            (expected, actual)
            for (expected, actual), count in totals.items()
            for _ in range(count)
        ]
    )
    return {
        "sample_count": len(case_reports),
        "risk_count": total_count,
        "correct_count": correct_count,
        "missing_prediction_count": missing_count,
        "overall": overall_metrics,
        "cases": case_reports,
    }


def _prediction_items(prediction: Mapping[str, Any]) -> dict[str, str]:
    evidence = prediction.get("evidence", [])
    if not isinstance(evidence, list):
        raise ValueError("预测 evidence 必须是数组")
    result: dict[str, str] = {}
    for index, item in enumerate(evidence):
        if not isinstance(item, Mapping):
            raise ValueError(f"预测 evidence[{index}] 必须是对象")
        risk_key = str(item.get("risk_key", "")).strip()
        status = str(item.get("support_relation_status", "")).strip()
        if not risk_key or status not in SUPPORT_STATUSES:
            raise ValueError(f"预测 evidence[{index}] 缺少有效 risk_key 或状态")
        if risk_key in result:
            raise ValueError(f"预测 evidence risk_key 重复: {risk_key}")
        result[risk_key] = status
    return result


def _classification_metrics(pairs: Sequence[tuple[str, str | None]]) -> dict[str, float]:
    per_status: dict[str, dict[str, float]] = {}
    f1_values: list[float] = []
    for status in SUPPORT_STATUSES:
        true_positive = sum(expected == status and actual == status for expected, actual in pairs)
        false_positive = sum(expected != status and actual == status for expected, actual in pairs)
        false_negative = sum(expected == status and actual != status for expected, actual in pairs)
        precision = _ratio(true_positive, true_positive + false_positive)
        recall = _ratio(true_positive, true_positive + false_negative)
        f1 = _ratio(2 * precision * recall, precision + recall)
        per_status[status] = {"precision": precision, "recall": recall, "f1": f1}
        f1_values.append(f1)
    correct = sum(expected == actual for expected, actual in pairs)
    return {
        "accuracy": _ratio(correct, len(pairs)),
        "macro_f1": sum(f1_values) / len(f1_values),
        "by_status": per_status,
    }


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0
