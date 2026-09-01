"""合同要素人工金标准评测。"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from jsonschema import Draft202012Validator


SCALAR_FIELDS = ("party_a", "party_b", "subject", "amount", "duration")
MULTIVALUE_FIELDS = ("payment_terms",)
REQUIRED_GOLD_FIELDS = SCALAR_FIELDS + MULTIVALUE_FIELDS
_SCHEMA_PATH = Path(__file__).with_name("schema.json")
_GOLD_SCHEMA = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
_GOLD_VALIDATOR = Draft202012Validator(_GOLD_SCHEMA)


def normalize_scalar(value: Any) -> str:
    """只做不改变业务语义的 Unicode 与空白规范化。"""
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKC", str(value))
    return re.sub(r"\s+", " ", normalized).strip()


def scalar_accuracy(gold: Sequence[Any], predicted: Sequence[Any]) -> float:
    if len(gold) != len(predicted):
        raise ValueError("金标准与预测数量不一致")
    if not gold:
        return 0.0
    correct = sum(
        normalize_scalar(expected) == normalize_scalar(actual)
        for expected, actual in zip(gold, predicted)
    )
    return correct / len(gold)


def _normalized_values(values: Any) -> set[str]:
    if values is None:
        return set()
    source = values if isinstance(values, (list, tuple, set)) else (values,)
    return {normalized for item in source if (normalized := normalize_scalar(item))}


def multivalue_metrics(gold: Any, predicted: Any) -> dict[str, float]:
    expected = _normalized_values(gold)
    actual = _normalized_values(predicted)
    if not expected and not actual:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    true_positive = len(expected & actual)
    precision = true_positive / len(actual) if actual else 0.0
    recall = true_positive / len(expected) if expected else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def validate_gold_record(record: Mapping[str, Any]) -> None:
    errors = sorted(
        _GOLD_VALIDATOR.iter_errors(record),
        key=lambda item: [str(part) for part in item.absolute_path],
    )
    if not errors:
        return
    first = errors[0]
    location = ".".join(str(part) for part in first.absolute_path) or "$"
    raise ValueError(f"金标准不符合 schema.json: {location}: {first.message}")


def dataset_sha256(records: Sequence[Mapping[str, Any]]) -> str:
    canonical = json.dumps(
        records,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _mean_metrics(items: Iterable[Mapping[str, float]]) -> dict[str, float]:
    values = list(items)
    if not values:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    return {
        name: sum(item[name] for item in values) / len(values)
        for name in ("precision", "recall", "f1")
    }


def _summarize_cases(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    metrics = [metric for case in cases for metric in case["field_metrics"].values()]
    return {"sample_count": len(cases), **_mean_metrics(metrics)}


def evaluate_dataset(
    gold_records: Sequence[Mapping[str, Any]],
    predictions: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """按字段宏平均评测，并保留每个错误案例的原始值。"""
    for record in gold_records:
        validate_gold_record(record)
    gold_case_ids = {str(record["case_id"]) for record in gold_records}
    unknown_ids = sorted(set(predictions) - gold_case_ids)
    if unknown_ids:
        raise ValueError(f"预测集包含未知 case_id: {', '.join(unknown_ids)}")

    seen: set[str] = set()
    cases: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    field_metrics: dict[str, list[dict[str, float]]] = defaultdict(list)

    for record in gold_records:
        case_id = str(record["case_id"])
        if case_id in seen:
            raise ValueError(f"case_id 重复: {case_id}")
        seen.add(case_id)
        gold = record["gold"]
        predicted = predictions.get(case_id, {})
        current: dict[str, dict[str, float]] = {}

        for field in REQUIRED_GOLD_FIELDS:
            if field in MULTIVALUE_FIELDS:
                metrics = multivalue_metrics(gold[field], predicted.get(field))
            else:
                matched = float(
                    normalize_scalar(gold[field]) == normalize_scalar(predicted.get(field))
                )
                metrics = {"precision": matched, "recall": matched, "f1": matched}
            current[field] = metrics
            field_metrics[field].append(metrics)
            if metrics["f1"] < 1.0:
                errors.append(
                    {
                        "case_id": case_id,
                        "field": field,
                        "gold": gold[field],
                        "predicted": predicted.get(field),
                    }
                )

        cases.append(
            {
                "case_id": case_id,
                "file": record["file"],
                "contract_type": record["contract_type"],
                "document_kind": record["document_kind"],
                "field_metrics": current,
            }
        )

    by_contract: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_document: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        by_contract[str(case["contract_type"])].append(case)
        by_document[str(case["document_kind"])].append(case)

    return {
        "dataset_sha256": dataset_sha256(gold_records),
        "sample_count": len(cases),
        "overall": _summarize_cases(cases),
        "by_field": {
            field: {"sample_count": len(values), **_mean_metrics(values)}
            for field, values in field_metrics.items()
        },
        "by_contract_type": {
            name: _summarize_cases(group) for name, group in sorted(by_contract.items())
        },
        "by_document_kind": {
            name: _summarize_cases(group) for name, group in sorted(by_document.items())
        },
        "errors": errors,
        "cases": cases,
    }
