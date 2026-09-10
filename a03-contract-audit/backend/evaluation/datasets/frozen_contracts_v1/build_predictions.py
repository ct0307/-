"""调用当前生产解析器生成冻结集六要素预测与解析元数据。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.services.parser.extractor import extract_document, extract_elements


FIELDS = ("party_a", "party_b", "subject", "amount", "duration", "payment_terms")


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _payment_terms(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def build_predictions(dataset_root: Path) -> list[dict[str, Any]]:
    root = Path(dataset_root).resolve()
    truth_rows = _jsonl(root / "construction-truth.jsonl")
    predictions: list[dict[str, Any]] = []
    for truth in truth_rows:
        path = root / str(truth["file"])
        case_id = str(truth["case_id"])
        try:
            parsed = extract_document(str(path))
            extracted = extract_elements(parsed.text)
            prediction = {field: extracted.get(field) for field in FIELDS}
            prediction["payment_terms"] = _payment_terms(prediction["payment_terms"])
            predictions.append(
                {
                    "case_id": case_id,
                    "prediction": prediction,
                    "parse": {
                        "status": "parsed",
                        "source": parsed.source,
                        "text_length": len(parsed.text),
                        "ocr_confidence": parsed.ocr_confidence,
                        "requires_review": parsed.requires_review,
                        "review_reason": parsed.review_reason,
                    },
                }
            )
        except Exception as exc:
            predictions.append(
                {
                    "case_id": case_id,
                    "prediction": {},
                    "parse": {
                        "status": "failed",
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:500],
                    },
                }
            )
    return predictions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    args = parser.parse_args()
    root = args.dataset.resolve()
    predictions = build_predictions(root)
    output = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        for row in predictions
    )
    (root / "predictions.jsonl").write_text(output, encoding="utf-8")
    parsed = sum(row["parse"]["status"] == "parsed" for row in predictions)
    failed = len(predictions) - parsed
    print(f"predictions={len(predictions)} parsed={parsed} failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
