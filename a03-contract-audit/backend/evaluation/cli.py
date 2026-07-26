"""要素准确率命令行入口。"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from evaluation.elements import evaluate_dataset


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number} 不是有效 JSON") from exc
    return records


def _write_csv(path: Path, report: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(
            target,
            fieldnames=("case_id", "file", "contract_type", "document_kind", "field", "precision", "recall", "f1"),
        )
        writer.writeheader()
        for case in report["cases"]:
            for field, metrics in case["field_metrics"].items():
                writer.writerow(
                    {
                        "case_id": case["case_id"],
                        "file": case["file"],
                        "contract_type": case["contract_type"],
                        "document_kind": case["document_kind"],
                        "field": field,
                        **metrics,
                    }
                )


def main() -> int:
    parser = argparse.ArgumentParser(description="基于人工金标准评测合同要素准确率")
    parser.add_argument("--gold", type=Path, required=True, help="人工金标准 JSONL")
    parser.add_argument("--predictions", type=Path, required=True, help="预测结果 JSONL")
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    args = parser.parse_args()

    gold_records = _read_jsonl(args.gold)
    prediction_records = _read_jsonl(args.predictions)
    predictions: dict[str, dict[str, Any]] = {}
    for record in prediction_records:
        case_id = str(record.get("case_id", ""))
        if not case_id or not isinstance(record.get("prediction"), dict):
            raise ValueError("预测记录必须包含 case_id 和 prediction 对象")
        if case_id in predictions:
            raise ValueError(f"预测 case_id 重复: {case_id}")
        predictions[case_id] = record["prediction"]

    report = evaluate_dataset(gold_records, predictions)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_csv(args.output_csv, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
