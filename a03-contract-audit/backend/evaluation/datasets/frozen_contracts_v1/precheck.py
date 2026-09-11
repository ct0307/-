"""对构造真值执行技术预评测，永不生成正式金标准结论。"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from evaluation.elements import REQUIRED_GOLD_FIELDS, multivalue_metrics, normalize_scalar


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def evaluate_construction_truth(
    truth_rows: Sequence[Mapping[str, Any]],
    predictions: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    field_scores: dict[str, list[float]] = defaultdict(list)
    cases: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    known_ids = {str(row["case_id"]) for row in truth_rows}
    unknown = sorted(set(predictions) - known_ids)
    if unknown:
        raise ValueError(f"预测集包含未知 case_id: {', '.join(unknown)}")

    for row in truth_rows:
        case_id = str(row["case_id"])
        gold = row["gold"]
        predicted = predictions.get(case_id, {})
        current: dict[str, float] = {}
        for field in REQUIRED_GOLD_FIELDS:
            if field == "payment_terms":
                score = multivalue_metrics(gold[field], predicted.get(field))["f1"]
            else:
                score = float(
                    normalize_scalar(gold[field])
                    == normalize_scalar(predicted.get(field))
                )
            current[field] = score
            field_scores[field].append(score)
            if score < 1.0:
                errors.append({"case_id": case_id, "field": field})
        cases.append({"case_id": case_id, "field_f1": current, "f1": _mean(list(current.values()))})

    by_field = {
        field: {"sample_count": len(scores), "f1": _mean(scores)}
        for field, scores in field_scores.items()
    }
    overall_scores = [score for scores in field_scores.values() for score in scores]
    return {
        "evidence_level": "construction_truth_only",
        "formal_gold": False,
        "threshold_claim": None,
        "sample_count": len(cases),
        "overall": {"f1": _mean(overall_scores)},
        "by_field": by_field,
        "errors": errors,
        "cases": cases,
    }


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    args = parser.parse_args()
    root = args.dataset.resolve()
    truth = _jsonl(root / "construction-truth.jsonl")
    prediction_rows = _jsonl(root / "predictions.jsonl")
    predictions = {row["case_id"]: row.get("prediction", {}) for row in prediction_rows}
    report = evaluate_construction_truth(truth, predictions)
    (root / "precheck-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["overall"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
