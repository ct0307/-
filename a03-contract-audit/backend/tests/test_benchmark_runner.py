"""OpenClaw/GPU 基准必须执行同口径 3+5 完整数据集轮次。"""
from dataclasses import dataclass
import json
from threading import Lock
import time

import pytest

from evaluation.benchmark import BenchmarkConfig
from evaluation.benchmark_runner import (
    BenchmarkCase,
    InvocationResult,
    compare_target_results,
    dataset_sha256,
    load_benchmark_manifest,
    run_target,
)
from evaluation.evidence import EvidenceWriter


@dataclass
class FakeTarget:
    latency_ms: float
    calls: list[tuple[str, str]]

    def invoke(self, phase: str, case: BenchmarkCase) -> InvocationResult:
        self.calls.append((phase, case.case_id))
        return InvocationResult(
            latency_ms=self.latency_ms,
            prompt_tokens=10,
            completion_tokens=5,
            error=None,
        )


def _cases() -> tuple[BenchmarkCase, ...]:
    return (
        BenchmarkCase(case_id="case-1", prompt="prompt-private-1"),
        BenchmarkCase(case_id="case-2", prompt="prompt-private-2"),
    )


def _config(target: str, cases: tuple[BenchmarkCase, ...] | None = None) -> BenchmarkConfig:
    selected = cases or _cases()
    return BenchmarkConfig(
        target=target,
        model_sha256="model-hash",
        prompt_version="prompt-v1",
        dataset_sha256=dataset_sha256(selected),
        context_length=8192,
        concurrency=1,
        output_schema_sha256="schema-hash",
    )


class ConcurrentTarget:
    def __init__(self):
        self.active = 0
        self.max_active = 0
        self.lock = Lock()

    def invoke(self, phase: str, case: BenchmarkCase) -> InvocationResult:
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.01)
        with self.lock:
            self.active -= 1
        return InvocationResult(10.0, 1, 1, None)


def _write_manifest(tmp_path, *, dataset_hash: str | None = None):
    cases = _cases()
    path = tmp_path / "benchmark-manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "model": "qwen-test",
                "model_sha256": "model-hash",
                "prompt_version": "prompt-v1",
                "dataset_sha256": dataset_hash or dataset_sha256(cases),
                "context_length": 8192,
                "concurrency": 1,
                "output_schema_sha256": "schema-hash",
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
    return path


def test_runner_executes_three_warmups_and_five_measured_dataset_rounds():
    calls: list[tuple[str, str]] = []
    cases = _cases()

    result = run_target(
        _config("openclaw", cases),
        cases,
        target=FakeTarget(10.0, calls),
        writer=None,
    )

    assert len([call for call in calls if call[0] == "warmup"]) == 6
    assert len([call for call in calls if call[0] == "measured"]) == 10
    assert result.warmup_rounds == 3
    assert result.measured_rounds == 5
    assert result.summary["total_runs"] == 10


def test_runner_rejects_dataset_hash_mismatch():
    cases = _cases()
    config = BenchmarkConfig(
        **{**_config("openclaw", cases).__dict__, "dataset_sha256": "wrong"}
    )

    with pytest.raises(ValueError, match="dataset_sha256"):
        run_target(config, cases, target=FakeTarget(10.0, []), writer=None)


def test_runner_applies_configured_concurrency_within_each_round():
    cases = _cases()
    config = BenchmarkConfig(**{**_config("openclaw", cases).__dict__, "concurrency": 2})
    target = ConcurrentTarget()

    run_target(config, cases, target=target, writer=None)

    assert target.max_active == 2


def test_manifest_rejects_round_counts_other_than_three_and_five(tmp_path):
    path = _write_manifest(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["measured_runs"] = 1
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="3 次预热和 5 次正式"):
        load_benchmark_manifest(path)


def test_manifest_rejects_dataset_hash_mismatch(tmp_path):
    with pytest.raises(ValueError, match="dataset_sha256"):
        load_benchmark_manifest(_write_manifest(tmp_path, dataset_hash="wrong"))


def test_comparison_passes_only_when_openclaw_is_not_less_reliable_and_faster():
    cases = _cases()
    openclaw = run_target(
        _config("openclaw", cases),
        cases,
        target=FakeTarget(10.0, []),
        writer=None,
    )
    gpu = run_target(
        _config("gpu", cases),
        cases,
        target=FakeTarget(20.0, []),
        writer=None,
    )

    comparison = compare_target_results(openclaw, gpu)

    assert comparison.status == "passed"
    assert comparison.openclaw_success_rate >= comparison.gpu_success_rate
    assert comparison.openclaw_p95 < comparison.gpu_p95


def test_benchmark_evidence_omits_prompts_and_response_content(tmp_path):
    cases = _cases()
    writer = EvidenceWriter.create(
        tmp_path,
        run_id="benchmark-run",
        command="benchmark",
        git_commit="abc123",
        git_dirty=False,
    )

    run_target(
        _config("openclaw", cases),
        cases,
        target=FakeTarget(10.0, []),
        writer=writer,
    )
    evidence = (writer.run_dir / "benchmark.jsonl").read_text(encoding="utf-8")

    assert "prompt-private" not in evidence
    assert "response" not in evidence
    assert '"case_id": "case-1"' in evidence
    assert '"phase": "warmup"' in evidence
