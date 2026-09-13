"""硬指标 CLI 必须使用稳定退出码并生成脱敏证据。"""
import hashlib
import json
from pathlib import Path

import pytest

from evaluation.batch import BatchSubmission
from evaluation.benchmark_runner import BenchmarkCase, InvocationResult, dataset_sha256
from evaluation.cli import EXIT_BLOCKED, EXIT_FAILED, EXIT_INVALID, EXIT_OK, main


def _gold_row() -> dict:
    return {
        "case_id": "case-1",
        "file": "case-1.pdf",
        "contract_type": "采购合同",
        "document_kind": "pdf",
        "reviewers": ["reviewer-a", "reviewer-b"],
        "review_status": "agreed",
        "version": "v1",
        "gold": {
            "party_a": "甲公司",
            "party_b": "乙公司",
            "subject": "设备采购",
            "amount": "100万元",
            "duration": "12个月",
            "payment_terms": ["首付款", "验收款"],
        },
    }


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    return path


def _audit_gold(case_id: str = "audit-case-1", *, basis: str = "human_gold") -> dict:
    return {
        "case_id": case_id,
        "evaluation_basis": basis,
        **(
            {"reviewers": ["legal-a", "legal-b"], "review_status": "agreed"}
            if basis == "human_gold"
            else {}
        ),
        "risks": [
            {
                "gold_risk_id": f"{case_id}-gold-1",
                "severity": "high",
                "category": "payment",
                "location": {"clause_id": "clause-2", "start": 5, "end": 12},
                "evidence_ids": ["LAW-509"],
            }
        ],
    }


def _audit_prediction(case_id: str = "audit-case-1", *, cost: float | None = 0.01) -> dict:
    call = {
        "json_valid": True,
        "prompt_tokens": 80,
        "completion_tokens": 20,
        "latency_ms": 50,
    }
    if cost is not None:
        call["cost"] = cost
    return {
        "case_id": case_id,
        "status": "done",
        "risks": [
            {
                "candidate_id": f"{case_id}-candidate-1",
                "matched_gold_id": f"{case_id}-gold-1",
                "quote_located": True,
                "invalid_legal_citation": False,
            }
        ],
        "finish_reasons": ["stop"],
        "coverage": {"completed": 1, "total": 1},
        "calls": [call],
        "currency": "CNY",
        "pricing_source": "provider-price-page",
        "pricing_version": "2026-09-01",
        "contract_text": "不得写入证据的合同正文",
        "prompt": "不得写入证据的提示词",
        "response": "不得写入证据的响应",
    }


def _audit_summary(
    name: str,
    *,
    high_recall: float = 1.0,
    cost: float | None = 0.01,
    basis: str = "human_gold",
) -> dict:
    return {
        "candidate": name,
        "sample_count": 1,
        "evaluation_basis": basis,
        "input_hashes": {
            "gold_sha256": "a" * 64,
            "predictions_sha256": "b" * 64,
        },
        "overall": {
            "high_risk_recall": high_recall,
            "risk_recall": 1.0,
            "risk_precision": 1.0,
            "quote_location_rate": 1.0,
            "invalid_legal_citation_rate": 0.0,
            "json_valid_rate": 1.0,
            "final_truncation_rate": 0.0,
            "false_success_rate": 0.0,
            "manual_review_rate": 0.0,
            "mean_prompt_tokens": 80.0,
            "mean_completion_tokens": 20.0,
            "mean_cost_per_success": cost,
            "p95_latency_ms": 50.0,
        },
        "cost_evidence_complete": cost is not None,
        "cost_metadata": (
            {
                "currency": "CNY",
                "pricing_source": "provider-price-page",
                "pricing_version": "2026-09-01",
            }
            if cost is not None
            else None
        ),
        "experiment": {
            "group": name,
            "git_commit": "94c8f9f" if name == "A" else f"{name.lower()}-commit",
            "change_scope": {
                "A": "baseline",
                "B": "output_budget_only",
                "C": "selective_cascade",
            }.get(name, "invalid"),
            "output_budget": {"A": 1600, "B": 2400, "C": 1600}.get(name, 1600),
            "frozen_context": {
                "model_version": "model-v1",
                "prompt_version": "prompt-v1",
                "knowledge_base_version": "kb-v1",
                "dataset_version": "dataset-v1",
                "temperature": 0.2,
                "environment": "test-env",
            },
        },
    }


def _audit_experiment(group: str) -> dict:
    return {
        "group": group,
        "git_commit": "94c8f9f" if group == "A" else f"{group.lower()}-commit",
        "change_scope": {
            "A": "baseline",
            "B": "output_budget_only",
            "C": "selective_cascade",
        }[group],
        "output_budget": {"A": 1600, "B": 2400, "C": 1600}[group],
        "frozen_context": {
            "model_version": "model-v1",
            "prompt_version": "prompt-v1",
            "knowledge_base_version": "kb-v1",
            "dataset_version": "dataset-v1",
            "temperature": 0.2,
            "environment": "test-env",
        },
    }


def _create_audit_run(
    tmp_path: Path,
    group: str,
    *,
    basis: str = "human_gold",
    cost: float | None = 0.01,
    quality_passed: bool = True,
) -> Path:
    gold = _write_jsonl(tmp_path / f"audit-{group}-gold.jsonl", [_audit_gold(basis=basis)])
    prediction = _audit_prediction(cost=cost)
    prediction["experiment"] = _audit_experiment(group)
    if not quality_passed:
        prediction["risks"] = []
    predictions = _write_jsonl(
        tmp_path / f"audit-{group}-predictions.jsonl", [prediction]
    )
    run_id = f"audit-candidate-{group}"
    code = main(
        [
            "audit-quality",
            "--gold",
            str(gold),
            "--predictions",
            str(predictions),
            "--runs-root",
            str(tmp_path / "candidate-runs"),
            "--run-id",
            run_id,
        ]
    )
    assert code == (EXIT_OK if quality_passed else EXIT_FAILED)
    return tmp_path / "candidate-runs" / run_id / "audit-summary.json"


def _invoke_elements(tmp_path: Path, *, gold: dict, prediction: dict, run_id: str) -> int:
    gold_path = _write_jsonl(tmp_path / f"{run_id}-gold.jsonl", [gold])
    predictions_path = _write_jsonl(
        tmp_path / f"{run_id}-predictions.jsonl",
        [{"case_id": gold["case_id"], "prediction": prediction}],
    )
    return main(
        [
            "elements",
            "--gold",
            str(gold_path),
            "--predictions",
            str(predictions_path),
            "--runs-root",
            str(tmp_path / "runs"),
            "--run-id",
            run_id,
            "--min-f1",
            "0.90",
        ]
    )


def _write_batch_manifest(tmp_path: Path) -> Path:
    samples = []
    for index in range(50):
        path = tmp_path / f"batch-valid-{index}.txt"
        path.write_text("合同", encoding="utf-8")
        samples.append(
            {
                "path": path.name,
                "role": "valid",
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "expected_status": "done",
            }
        )
    for index in range(2):
        path = tmp_path / f"batch-invalid-{index}.exe"
        path.write_bytes(b"invalid")
        samples.append(
            {
                "path": path.name,
                "role": "invalid",
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "expected_status": 400,
            }
        )
    manifest = tmp_path / "batch-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "contract_type": "采购合同",
                "dimensions": ["legal"],
                "samples": samples,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return manifest


class _CliBatchGateway:
    def __init__(self, *_args, **_kwargs):
        self.submission_sizes = []

    def close(self):
        return None

    def submit(self, samples, **_kwargs):
        self.submission_sizes.append(len(samples))
        if samples[0].role == "invalid":
            return BatchSubmission(None, 400, {})
        return BatchSubmission(7, 202, {"id": 7})

    def get(self, batch_id):
        return {
            "id": batch_id,
            "status": "done",
            "total": 50,
            "completed": 50,
            "failed": 0,
            "items": [{"id": index, "status": "done"} for index in range(50)],
        }


def _write_benchmark_manifest(tmp_path: Path) -> Path:
    cases = (
        BenchmarkCase("case-1", "private-prompt-1"),
        BenchmarkCase("case-2", "private-prompt-2"),
    )
    manifest = tmp_path / "benchmark-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "model": "qwen-test",
                "model_sha256": "d" * 64,
                "prompt_version": "prompt-v1",
                "dataset_sha256": dataset_sha256(cases),
                "context_length": 8192,
                "concurrency": 1,
                "output_schema_sha256": "e" * 64,
                "warmup_runs": 3,
                "measured_runs": 5,
                "cases": [
                    {"case_id": case.case_id, "prompt": case.prompt} for case in cases
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return manifest


class _CliBenchmarkTarget:
    instances = []

    def __init__(self, base_url, **_kwargs):
        self.latency_ms = 10.0 if "openclaw" in base_url else 20.0
        self.calls = []
        self.__class__.instances.append(self)

    def close(self):
        return None

    def invoke(self, phase, case):
        self.calls.append((phase, case.case_id))
        return InvocationResult(self.latency_ms, 10, 5, None)


def test_elements_command_returns_ok_and_writes_passed_manifest(tmp_path):
    gold = _gold_row()

    code = _invoke_elements(
        tmp_path,
        gold=gold,
        prediction=gold["gold"],
        run_id="elements-pass",
    )
    manifest = json.loads(
        (tmp_path / "runs" / "elements-pass" / "manifest.json").read_text(encoding="utf-8")
    )

    assert code == EXIT_OK
    assert manifest["status"] == "passed"
    assert manifest["modules"] == {"elements": "passed"}
    assert manifest["inputs"]["sample_count"] == 1


def test_elements_command_returns_failed_when_f1_is_below_threshold(tmp_path):
    gold = _gold_row()
    prediction = {**gold["gold"], "party_b": "错误公司"}

    code = _invoke_elements(
        tmp_path,
        gold=gold,
        prediction=prediction,
        run_id="elements-low",
    )
    manifest = json.loads(
        (tmp_path / "runs" / "elements-low" / "manifest.json").read_text(encoding="utf-8")
    )

    assert code == EXIT_FAILED
    assert manifest["status"] == "failed"
    assert manifest["modules"] == {"elements": "failed"}


def test_elements_command_returns_invalid_for_bad_gold_without_creating_run(tmp_path):
    gold = _gold_row()
    gold["document_kind"] = "jpg"

    code = _invoke_elements(
        tmp_path,
        gold=gold,
        prediction=gold["gold"],
        run_id="elements-invalid",
    )

    assert code == EXIT_INVALID
    assert not (tmp_path / "runs" / "elements-invalid").exists()


def test_elements_command_returns_invalid_for_empty_gold(tmp_path):
    gold_path = _write_jsonl(tmp_path / "empty-gold.jsonl", [])
    predictions_path = _write_jsonl(tmp_path / "empty-predictions.jsonl", [])

    code = main(
        [
            "elements",
            "--gold",
            str(gold_path),
            "--predictions",
            str(predictions_path),
            "--runs-root",
            str(tmp_path / "runs"),
            "--run-id",
            "empty-run",
        ]
    )

    assert code == EXIT_INVALID
    assert not (tmp_path / "runs" / "empty-run").exists()


def test_elements_command_refuses_duplicate_run_id(tmp_path):
    gold = _gold_row()
    first = _invoke_elements(tmp_path, gold=gold, prediction=gold["gold"], run_id="same-run")
    second = _invoke_elements(tmp_path, gold=gold, prediction=gold["gold"], run_id="same-run")

    assert first == EXIT_OK
    assert second == EXIT_INVALID


def test_elements_evidence_does_not_store_raw_field_values(tmp_path):
    gold = _gold_row()

    _invoke_elements(tmp_path, gold=gold, prediction=gold["gold"], run_id="redacted-run")
    evidence = (tmp_path / "runs" / "redacted-run" / "elements.jsonl").read_text(
        encoding="utf-8"
    )

    assert "甲公司" not in evidence
    assert "乙公司" not in evidence
    assert "100万元" not in evidence
    assert "case-1" in evidence


def test_batch_command_uses_gateway_and_writes_passed_manifest(monkeypatch, tmp_path):
    monkeypatch.setenv("A03_EVAL_TOKEN", "secret-token")
    gateway = _CliBatchGateway()
    monkeypatch.setattr("evaluation.cli.HttpBatchGateway", lambda *_args, **_kwargs: gateway)

    code = main(
        [
            "batch",
            "--manifest",
            str(_write_batch_manifest(tmp_path)),
            "--base-url",
            "http://127.0.0.1:8000/api/v1",
            "--runs-root",
            str(tmp_path / "runs"),
            "--run-id",
            "batch-pass",
            "--poll-interval",
            "0",
        ]
    )
    manifest = json.loads(
        (tmp_path / "runs" / "batch-pass" / "manifest.json").read_text(encoding="utf-8")
    )

    assert code == EXIT_OK
    assert gateway.submission_sizes == [50, 1, 1]
    assert manifest["status"] == "passed"
    assert manifest["modules"] == {"batch": "passed"}
    assert main(["report", "--run-dir", str(tmp_path / "runs" / "batch-pass")]) == EXIT_OK


def test_batch_command_is_blocked_when_token_is_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("A03_EVAL_TOKEN", raising=False)

    code = main(
        [
            "batch",
            "--manifest",
            str(_write_batch_manifest(tmp_path)),
            "--base-url",
            "http://127.0.0.1:8000/api/v1",
            "--runs-root",
            str(tmp_path / "runs"),
            "--run-id",
            "batch-blocked",
        ]
    )
    manifest = json.loads(
        (tmp_path / "runs" / "batch-blocked" / "manifest.json").read_text(encoding="utf-8")
    )

    assert code == EXIT_BLOCKED
    assert manifest["status"] == "blocked"
    assert manifest["modules"] == {"batch": "blocked"}


def test_benchmark_command_compares_two_targets_and_writes_passed_manifest(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("OPENCLAW_EVAL_KEY", "openclaw-secret")
    monkeypatch.setenv("GPU_EVAL_KEY", "gpu-secret")
    _CliBenchmarkTarget.instances = []
    monkeypatch.setattr("evaluation.cli.OpenAICompatibleTarget", _CliBenchmarkTarget)

    code = main(
        [
            "benchmark",
            "--manifest",
            str(_write_benchmark_manifest(tmp_path)),
            "--openclaw-url",
            "http://openclaw/v1",
            "--gpu-url",
            "http://gpu/v1",
            "--runs-root",
            str(tmp_path / "runs"),
            "--run-id",
            "benchmark-pass",
        ]
    )
    manifest = json.loads(
        (tmp_path / "runs" / "benchmark-pass" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )

    assert code == EXIT_OK
    assert [len(target.calls) for target in _CliBenchmarkTarget.instances] == [16, 16]
    assert manifest["status"] == "passed"
    assert manifest["modules"] == {"benchmark": "passed"}
    assert (
        main(["report", "--run-dir", str(tmp_path / "runs" / "benchmark-pass")])
        == EXIT_OK
    )


def test_benchmark_command_is_blocked_when_key_is_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENCLAW_EVAL_KEY", raising=False)
    monkeypatch.setenv("GPU_EVAL_KEY", "gpu-secret")

    code = main(
        [
            "benchmark",
            "--manifest",
            str(_write_benchmark_manifest(tmp_path)),
            "--openclaw-url",
            "http://openclaw/v1",
            "--gpu-url",
            "http://gpu/v1",
            "--runs-root",
            str(tmp_path / "runs"),
            "--run-id",
            "benchmark-blocked",
        ]
    )
    manifest = json.loads(
        (tmp_path / "runs" / "benchmark-blocked" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )

    assert code == EXIT_BLOCKED
    assert manifest["status"] == "blocked"
    assert manifest["modules"] == {"benchmark": "blocked"}


def test_report_command_builds_report_for_complete_run(tmp_path):
    gold = _gold_row()
    assert (
        _invoke_elements(
            tmp_path,
            gold=gold,
            prediction=gold["gold"],
            run_id="report-source",
        )
        == EXIT_OK
    )
    run_dir = tmp_path / "runs" / "report-source"

    code = main(["report", "--run-dir", str(run_dir)])

    assert code == EXIT_OK
    assert (run_dir / "report.md").is_file()


def test_report_command_returns_invalid_for_missing_event_stream(tmp_path):
    gold = _gold_row()
    _invoke_elements(
        tmp_path,
        gold=gold,
        prediction=gold["gold"],
        run_id="broken-report-source",
    )
    run_dir = tmp_path / "runs" / "broken-report-source"
    (run_dir / "elements.jsonl").unlink()

    code = main(["report", "--run-dir", str(run_dir)])

    assert code == EXIT_INVALID
    assert not (run_dir / "report.md").exists()


def test_retrieval_command_writes_metrics_and_builds_report(tmp_path):
    gold = _write_jsonl(
        tmp_path / "retrieval-gold.jsonl",
        [{"case_id": "q1", "relevant_ids": ["LAW-585"]}],
    )
    predictions = _write_jsonl(
        tmp_path / "retrieval-predictions.jsonl",
        [{"case_id": "q1", "ranked_ids": ["LAW-585", "LAW-577"]}],
    )

    code = main([
        "retrieval",
        "--gold", str(gold),
        "--predictions", str(predictions),
        "--runs-root", str(tmp_path / "runs"),
        "--run-id", "retrieval-pass",
        "--k", "5",
        "--min-recall", "0.90",
    ])
    run_dir = tmp_path / "runs" / "retrieval-pass"
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    evidence = (run_dir / "retrieval.jsonl").read_text(encoding="utf-8")

    assert code == EXIT_OK
    assert manifest["modules"] == {"retrieval": "passed"}
    assert manifest["inputs"]["min_recall"] == 0.90
    assert '"recall@5": 1.0' in evidence
    assert main(["report", "--run-dir", str(run_dir)]) == EXIT_OK
    assert "Recall@5" in (run_dir / "report.md").read_text(encoding="utf-8")


def test_audit_quality_command_writes_safe_summary_and_human_gold_report(tmp_path):
    gold = _write_jsonl(tmp_path / "audit-gold.jsonl", [_audit_gold()])
    predictions = _write_jsonl(
        tmp_path / "audit-predictions.jsonl", [_audit_prediction()]
    )

    code = main(
        [
            "audit-quality",
            "--gold",
            str(gold),
            "--predictions",
            str(predictions),
            "--runs-root",
            str(tmp_path / "runs"),
            "--run-id",
            "audit-pass",
        ]
    )
    run_dir = tmp_path / "runs" / "audit-pass"
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((run_dir / "audit-summary.json").read_text(encoding="utf-8"))
    evidence = (run_dir / "audit.jsonl").read_text(encoding="utf-8")

    assert code == EXIT_OK
    assert manifest["modules"] == {"audit": "passed"}
    assert manifest["inputs"]["sample_count"] == 1
    assert manifest["inputs"]["gold_sha256"] == summary["input_hashes"]["gold_sha256"]
    assert summary["quality_gate_failures"] == []
    assert "不得写入证据的合同正文" not in evidence
    assert main(["report", "--run-dir", str(run_dir)]) == EXIT_OK
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "人工金标准评测" in report
    assert "合成数据技术预评测" not in report


def test_audit_quality_command_marks_quality_failure_without_cost_selection(tmp_path):
    gold = _write_jsonl(tmp_path / "audit-gold.jsonl", [_audit_gold()])
    prediction = _audit_prediction()
    prediction["risks"] = []
    predictions = _write_jsonl(tmp_path / "audit-predictions.jsonl", [prediction])

    code = main(
        [
            "audit-quality",
            "--gold",
            str(gold),
            "--predictions",
            str(predictions),
            "--runs-root",
            str(tmp_path / "runs"),
            "--run-id",
            "audit-failed",
        ]
    )

    assert code == EXIT_FAILED
    summary = json.loads(
        (tmp_path / "runs" / "audit-failed" / "audit-summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["quality_gate_failures"] == [
        "high_risk_recall",
        "quote_location_rate",
        "invalid_legal_citation_rate",
        "risk_recall",
        "risk_precision",
    ]


def test_audit_compare_rejects_orphan_summary_without_run_evidence(tmp_path):
    orphan = tmp_path / "audit-summary.json"
    orphan.write_text(json.dumps(_audit_summary("A")), encoding="utf-8")

    code = main(
        [
            "audit-compare",
            "--candidate",
            f"A={orphan}",
            "--runs-root",
            str(tmp_path / "runs"),
            "--run-id",
            "orphan-summary",
        ]
    )

    assert code == EXIT_INVALID
    assert not (tmp_path / "runs" / "orphan-summary").exists()


@pytest.mark.parametrize("tampered_artifact", ["summary", "event", "manifest"])
def test_audit_compare_rejects_tampered_candidate_evidence(tmp_path, tampered_artifact):
    paths = [_create_audit_run(tmp_path, group) for group in "ABC"]
    run_dir = paths[0].parent
    if tampered_artifact == "summary":
        summary = json.loads(paths[0].read_text(encoding="utf-8"))
        summary["overall"]["high_risk_recall"] = 0.0
        paths[0].write_text(json.dumps(summary), encoding="utf-8")
    elif tampered_artifact == "event":
        events_path = run_dir / "audit.jsonl"
        events = [
            json.loads(line)
            for line in events_path.read_text(encoding="utf-8").splitlines()
        ]
        events[0]["payload"]["matched_risk_count"] = 0
        events_path.write_text(
            "".join(json.dumps(row) + "\n" for row in events), encoding="utf-8"
        )
    else:
        manifest_path = run_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["inputs"]["gold_sha256"] = "f" * 64
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    code = main(
        [
            "audit-compare",
            *[
                item
                for group, path in zip("ABC", paths)
                for item in ("--candidate", f"{group}={path}")
            ],
            "--runs-root",
            str(tmp_path / "runs"),
            "--run-id",
            f"tampered-{tampered_artifact}",
        ]
    )

    assert code == EXIT_INVALID
    assert not (tmp_path / "runs" / f"tampered-{tampered_artifact}").exists()


def test_audit_compare_selects_only_quality_passed_candidate_and_builds_report(tmp_path):
    candidate_a = _create_audit_run(
        tmp_path, "A", cost=0.001, quality_passed=False
    )
    candidate_b = _create_audit_run(tmp_path, "B", cost=0.02)
    candidate_c = _create_audit_run(tmp_path, "C", cost=0.03)

    code = main(
        [
            "audit-compare",
            "--candidate",
            f"A={candidate_a}",
            "--candidate",
            f"B={candidate_b}",
            "--candidate",
            f"C={candidate_c}",
            "--runs-root",
            str(tmp_path / "runs"),
            "--run-id",
            "compare-pass",
        ]
    )
    run_dir = tmp_path / "runs" / "compare-pass"
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    summary = json.loads(
        (run_dir / "audit-comparison-summary.json").read_text(encoding="utf-8")
    )

    assert code == EXIT_OK
    assert manifest["modules"] == {"audit_comparison": "passed"}
    assert summary["selected"] == "B"
    assert summary["evaluation_basis"] == "human_gold"
    assert summary["rejected"] == {
        "A": [
            "high_risk_recall",
            "quote_location_rate",
            "invalid_legal_citation_rate",
            "risk_recall",
            "risk_precision",
        ]
    }
    assert manifest["inputs"]["evaluation_basis"] == "human_gold"
    comparison_evidence = (run_dir / "audit-comparison.jsonl").read_text(encoding="utf-8")
    assert "不得进入比较证据的提示词" not in comparison_evidence
    assert "不得进入比较证据的响应" not in comparison_evidence
    assert main(["report", "--run-dir", str(run_dir)]) == EXIT_OK
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "`B`" in report
    assert "本次冻结模型、数据集和环境下最具性价比" in report


def test_audit_compare_returns_blocked_when_cost_evidence_is_incomplete(tmp_path):
    paths = [
        _create_audit_run(tmp_path, group, cost=None if group == "A" else 0.02)
        for group in "ABC"
    ]

    code = main(
        [
            "audit-compare",
            "--candidate",
            f"A={paths[0]}",
            "--candidate",
            f"B={paths[1]}",
            "--candidate",
            f"C={paths[2]}",
            "--runs-root",
            str(tmp_path / "runs"),
            "--run-id",
            "compare-inconclusive",
        ]
    )

    assert code == EXIT_BLOCKED
    run_dir = tmp_path / "runs" / "compare-inconclusive"
    summary = json.loads(
        (run_dir / "audit-comparison-summary.json").read_text(encoding="utf-8")
    )
    assert summary["status"] == "quality_passed_cost_inconclusive"
    assert summary["selected"] is None
    assert main(["report", "--run-dir", str(run_dir)]) == EXIT_BLOCKED
    assert "成本证据不足" in (run_dir / "report.md").read_text(encoding="utf-8")


def test_audit_compare_rejects_duplicate_or_unsafe_candidate_names(tmp_path):
    candidate = _create_audit_run(tmp_path, "A")
    candidate_c = _create_audit_run(tmp_path, "C")
    common = ["--runs-root", str(tmp_path / "runs")]

    code = main(
        [
            "audit-compare",
            "--candidate",
            f"A={candidate}",
            "--candidate",
            f"A={candidate}",
            "--candidate",
            f"C={candidate_c}",
            *common,
            "--run-id",
            "duplicate-candidates",
        ]
    )
    run_dir = tmp_path / "runs" / "duplicate-candidates"
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    summary = json.loads(
        (run_dir / "audit-comparison-summary.json").read_text(encoding="utf-8")
    )
    events = [
        json.loads(line)["payload"]
        for line in (run_dir / "audit-comparison.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert code == EXIT_FAILED
    assert summary["selected"] is None
    assert "candidate_name_duplicate" in summary["contract_errors"]
    assert manifest["inputs"]["candidate_names"] == ["A", "A", "C"]
    assert len(manifest["inputs"]["candidate_inputs"]) == 3
    assert [event["position"] for event in events if event["event"] == "candidate"] == [0, 1, 2]
    assert main(["report", "--run-dir", str(run_dir)]) == EXIT_FAILED

    assert (
        main(
            ["audit-compare", "--candidate", f"../outside={candidate}", *common]
        )
        == EXIT_INVALID
    )


def test_audit_compare_records_failed_result_for_mixed_evaluation_basis(tmp_path):
    paths = [
        _create_audit_run(
            tmp_path,
            group,
            basis="synthetic" if group == "A" else "human_gold",
        )
        for group in "ABC"
    ]

    code = main(
        [
            "audit-compare",
            "--candidate",
            f"A={paths[0]}",
            "--candidate",
            f"B={paths[1]}",
            "--candidate",
            f"C={paths[2]}",
            "--runs-root",
            str(tmp_path / "runs"),
            "--run-id",
            "mixed-basis",
        ]
    )
    run_dir = tmp_path / "runs" / "mixed-basis"

    assert code == EXIT_INVALID
    assert not run_dir.exists()


def test_synthetic_comparison_report_is_scoped_and_rejects_basis_tampering(tmp_path):
    arguments = ["audit-compare"]
    for group in "ABC":
        path = _create_audit_run(
            tmp_path, group, basis="synthetic", cost=ord(group) / 1000
        )
        arguments.extend(["--candidate", f"{group}={path}"])
    arguments.extend(
        [
            "--runs-root",
            str(tmp_path / "runs"),
            "--run-id",
            "synthetic-comparison",
        ]
    )

    assert main(arguments) == EXIT_OK
    run_dir = tmp_path / "runs" / "synthetic-comparison"
    assert main(["report", "--run-dir", str(run_dir)]) == EXIT_OK
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "合成数据技术预评测" in report
    assert "技术预评测范围内成本排序第一" in report
    assert "不代表人工准确率、真实合同效果或生产环境最优性价比" in report
    assert "本次冻结模型、数据集和环境下最具性价比" not in report

    events_path = run_dir / "audit-comparison.jsonl"
    rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    rows[0]["payload"]["evaluation_basis"] = "human_gold"
    events_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    assert main(["report", "--run-dir", str(run_dir)]) == EXIT_INVALID
