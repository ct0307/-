"""冻结后调用生产解析器生成 v2 六要素预测。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation.datasets.frozen_contracts_v1.build_predictions import build_predictions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    args = parser.parse_args()
    root = args.dataset.resolve()
    rows = build_predictions(root)
    (root / "predictions.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    parsed = sum(row["parse"]["status"] == "parsed" for row in rows)
    print(f"predictions={len(rows)} parsed={parsed} failed={len(rows) - parsed}")
    return 0 if parsed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
