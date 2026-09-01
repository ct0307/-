"""OpenClaw 与 GPU 基准必须使用同口径统计。"""
import pytest

from evaluation.benchmark import (
    BenchmarkConfig,
    assert_comparable,
    summarize_benchmark,
)


def _config(target: str) -> BenchmarkConfig:
    return BenchmarkConfig(
        target=target,
        model_sha256="model-hash",
        prompt_version="prompt-v1",
        dataset_sha256="dataset-hash",
        context_length=8192,
        concurrency=2,
        output_schema_sha256="schema-hash",
    )


def test_benchmark_reports_latency_throughput_success_and_confidence_interval():
    report = summarize_benchmark(
        latencies_ms=[100.0, 200.0, 300.0, None],
        wall_seconds=1.0,
        expected_runs=4,
    )

    assert report["total_runs"] == 4
    assert report["successful_runs"] == 3
    assert report["success_rate"] == 0.75
    assert report["throughput_per_second"] == 3.0
    assert report["latency_ms"]["p50"] == 200.0
    assert report["latency_ms"]["p95"] == pytest.approx(290.0)
    assert report["latency_ms"]["ci95"][0] < 200.0 < report["latency_ms"]["ci95"][1]


def test_benchmark_never_estimates_energy_without_samples():
    report = summarize_benchmark(latencies_ms=[100.0], wall_seconds=0.1, expected_runs=1)

    assert report["energy"] == {"status": "not_measured", "watt_hours": None}


def test_benchmark_rejects_different_model_hashes():
    gpu = _config("gpu")
    openclaw = _config("openclaw")
    openclaw = BenchmarkConfig(**{**openclaw.__dict__, "model_sha256": "other-model"})

    with pytest.raises(ValueError, match="model_sha256"):
        assert_comparable(gpu, openclaw)


def test_benchmark_accepts_same_protocol_for_different_targets():
    assert_comparable(_config("gpu"), _config("openclaw"))


def test_benchmark_rejects_incomplete_measured_runs():
    with pytest.raises(ValueError, match="正式运行记录数量应为 5"):
        summarize_benchmark(
            latencies_ms=[100.0],
            wall_seconds=0.1,
            expected_runs=5,
        )
