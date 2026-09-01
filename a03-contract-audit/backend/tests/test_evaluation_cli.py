"""硬指标 CLI 必须使用稳定退出码并生成脱敏证据。"""
import hashlib
import json
from pathlib import Path

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
