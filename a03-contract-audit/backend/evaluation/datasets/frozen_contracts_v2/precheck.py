"""按风险层级报告 v2 构造真值技术预评测。"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from evaluation.datasets.frozen_contracts_v1.precheck import evaluate_construction_truth as _evaluate


def evaluate_construction_truth(
    truth_rows: Sequence[Mapping[str, Any]],
    predictions: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    report = _evaluate(truth_rows, predictions)
    cases_by_id = {row["case_id"]: row for row in report["cases"]}
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in truth_rows:
        grouped[str(row["risk_level"])].append(cases_by_id[str(row["case_id"])]["f1"])
    report["by_risk_level"] = {
        level: {"sample_count": len(scores), "f1": sum(scores) / len(scores)}
        for level, scores in grouped.items()
    }
    return report


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    args = parser.parse_args()
    root = args.dataset.resolve()
    truth = _jsonl(root / "construction-truth.jsonl")
    predictions = {row["case_id"]: row.get("prediction", {}) for row in _jsonl(root / "predictions.jsonl")}
    report = evaluate_construction_truth(truth, predictions)
    (root / "precheck-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"overall": report["overall"], "by_risk_level": report["by_risk_level"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
