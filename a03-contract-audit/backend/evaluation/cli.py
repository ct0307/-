"""A03 硬指标证据流水线命令行入口。"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any, Sequence
import uuid

from evaluation.batch import (
    BatchTimeout,
    BatchUnavailable,
    HttpBatchGateway,
    load_batch_manifest,
    run_batch_acceptance,
)
from evaluation.elements import evaluate_dataset
from evaluation.evidence import EvidenceWriter, sha256_file


EXIT_OK = 0
EXIT_INVALID = 2
EXIT_ERROR = 3
EXIT_FAILED = 4
EXIT_BLOCKED = 5


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number} 不是有效 JSON") from exc
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} 必须是 JSON 对象")
            records.append(value)
    return records


def _read_predictions(path: Path) -> dict[str, dict[str, Any]]:
    predictions: dict[str, dict[str, Any]] = {}
    for record in _read_jsonl(path):
        case_id = str(record.get("case_id", ""))
        prediction = record.get("prediction")
        if not case_id or not isinstance(prediction, dict):
            raise ValueError("预测记录必须包含 case_id 和 prediction 对象")
        if case_id in predictions:
            raise ValueError(f"预测 case_id 重复: {case_id}")
        predictions[case_id] = prediction
    return predictions


def _default_run_id(command: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{command}-{timestamp}-{uuid.uuid4().hex[:8]}"


def _safe_elements_summary(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "event": "summary",
        "sample_count": report["sample_count"],
        "overall": report["overall"],
        "by_field": report["by_field"],
        "by_contract_type": report["by_contract_type"],
        "by_document_kind": report["by_document_kind"],
        "error_count": len(report["errors"]),
        "errors": [
            {"case_id": item["case_id"], "field": item["field"]}
            for item in report["errors"]
        ],
    }


def _run_elements(args: argparse.Namespace) -> int:
    if not 0 <= args.min_f1 <= 1:
        raise ValueError("--min-f1 必须在 0 到 1 之间")
    gold_records = _read_jsonl(args.gold)
    if not gold_records:
        raise ValueError("金标准 JSONL 不能为空")
    predictions = _read_predictions(args.predictions)
    report = evaluate_dataset(gold_records, predictions)
    run_id = args.run_id or _default_run_id("elements")
    writer = EvidenceWriter.create(
        args.runs_root,
        run_id=run_id,
        command="elements",
        inputs={
            "gold_sha256": sha256_file(args.gold),
            "predictions_sha256": sha256_file(args.predictions),
            "schema_sha256": sha256_file(Path(__file__).with_name("schema.json")),
            "sample_count": report["sample_count"],
            "min_f1": args.min_f1,
        },
    )
    for case in report["cases"]:
        writer.append(
            "elements",
            {
                "event": "case",
                "case_id": case["case_id"],
                "contract_type": case["contract_type"],
                "document_kind": case["document_kind"],
                "field_metrics": case["field_metrics"],
            },
        )
    writer.append("elements", _safe_elements_summary(report))
    status = "passed" if report["overall"]["f1"] >= args.min_f1 else "failed"
    writer.write_manifest(status=status, modules={"elements": status})
    return EXIT_OK if status == "passed" else EXIT_FAILED


def _run_batch(args: argparse.Namespace) -> int:
    manifest = load_batch_manifest(args.manifest)
    run_id = args.run_id or _default_run_id("batch")
    writer = EvidenceWriter.create(
        args.runs_root,
        run_id=run_id,
        command="batch",
        inputs={
            "manifest_sha256": sha256_file(args.manifest),
            "valid_count": 50,
            "invalid_count": 2,
        },
    )
    token = os.environ.get(args.token_env, "").strip()
    if not token:
        writer.append(
            "batch-events",
            {"event": "blocked", "reason": f"环境变量 {args.token_env} 未配置"},
        )
        writer.write_manifest(status="blocked", modules={"batch": "blocked"})
        return EXIT_BLOCKED

    gateway = HttpBatchGateway(
        args.base_url,
        token=token,
        timeout_seconds=args.request_timeout,
    )
    try:
        result = run_batch_acceptance(
            manifest,
            gateway=gateway,
            writer=writer,
            run_id=run_id,
            poll_interval=args.poll_interval,
            timeout_seconds=args.timeout_seconds,
        )
    except BatchUnavailable as exc:
        writer.append("batch-events", {"event": "blocked", "reason": str(exc)})
        writer.write_manifest(status="blocked", modules={"batch": "blocked"})
        return EXIT_BLOCKED
    except BatchTimeout as exc:
        writer.append("batch-events", {"event": "timeout", "reason": str(exc)})
        writer.write_manifest(status="failed", modules={"batch": "failed"})
        return EXIT_FAILED
    finally:
        gateway.close()

    writer.append(
        "batch-events",
        {
            "event": "summary",
            "status": result.status,
            "valid_count": result.valid_count,
            "invalid_count": result.invalid_count,
            "valid_batch_id": result.valid_batch_id,
            "reasons": list(result.reasons),
        },
    )
    writer.write_manifest(status=result.status, modules={"batch": result.status})
    return EXIT_OK if result.status == "passed" else EXIT_FAILED


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="A03 硬指标证据流水线")
    subcommands = parser.add_subparsers(dest="command", required=True)
    elements = subcommands.add_parser("elements", help="评测冻结金标准要素准确率")
    elements.add_argument("--gold", type=Path, required=True)
    elements.add_argument("--predictions", type=Path, required=True)
    elements.add_argument("--runs-root", type=Path, default=Path("evaluation-runs"))
    elements.add_argument("--run-id")
    elements.add_argument("--min-f1", type=float, default=0.90)
    batch = subcommands.add_parser("batch", help="执行 50+2 批量验收")
    batch.add_argument("--manifest", type=Path, required=True)
    batch.add_argument("--base-url", required=True)
    batch.add_argument("--token-env", default="A03_EVAL_TOKEN")
    batch.add_argument("--runs-root", type=Path, default=Path("evaluation-runs"))
    batch.add_argument("--run-id")
    batch.add_argument("--poll-interval", type=float, default=1.0)
    batch.add_argument("--timeout-seconds", type=float, default=900)
    batch.add_argument("--request-timeout", type=float, default=120)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "elements":
            return _run_elements(args)
        if args.command == "batch":
            return _run_batch(args)
        raise ValueError(f"未知子命令: {args.command}")
    except (FileExistsError, OSError, ValueError) as exc:
        print(f"输入无效: {exc}", file=sys.stderr)
        return EXIT_INVALID
    except Exception as exc:
        print(f"执行异常: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
