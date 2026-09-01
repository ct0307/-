"""OpenClaw/GPU 同口径基准统计，不生成任何模拟测量值。"""
from __future__ import annotations

from dataclasses import dataclass, fields
import math
from statistics import mean, stdev
from typing import Sequence


@dataclass(frozen=True)
class BenchmarkConfig:
    target: str
    model_sha256: str
    prompt_version: str
    dataset_sha256: str
    context_length: int
    concurrency: int
    output_schema_sha256: str
    warmup_runs: int = 3
    measured_runs: int = 5


@dataclass(frozen=True)
class PowerSample:
    timestamp_seconds: float
    power_watts: float


def assert_comparable(left: BenchmarkConfig, right: BenchmarkConfig) -> None:
    mismatches = [
        field.name
        for field in fields(BenchmarkConfig)
        if field.name != "target" and getattr(left, field.name) != getattr(right, field.name)
    ]
    if mismatches:
        raise ValueError(f"基准配置口径不一致: {', '.join(mismatches)}")


def _percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _energy_report(samples: Sequence[PowerSample] | None) -> dict[str, float | str | None]:
    if not samples or len(samples) < 2:
        return {"status": "not_measured", "watt_hours": None}
    ordered = sorted(samples, key=lambda sample: sample.timestamp_seconds)
    watt_seconds = 0.0
    for previous, current in zip(ordered, ordered[1:]):
        elapsed = current.timestamp_seconds - previous.timestamp_seconds
        if elapsed <= 0 or previous.power_watts < 0 or current.power_watts < 0:
            raise ValueError("功率时序必须按递增时间提供非负实测值")
        watt_seconds += elapsed * (previous.power_watts + current.power_watts) / 2
    return {"status": "measured", "watt_hours": watt_seconds / 3600.0}


def summarize_benchmark(
    *,
    latencies_ms: Sequence[float | None],
    wall_seconds: float,
    expected_runs: int,
    power_samples: Sequence[PowerSample] | None = None,
) -> dict[str, object]:
    if expected_runs <= 0:
        raise ValueError("expected_runs 必须大于 0")
    if len(latencies_ms) != expected_runs:
        raise ValueError(
            f"正式运行记录数量应为 {expected_runs}，实际为 {len(latencies_ms)}"
        )
    if wall_seconds <= 0:
        raise ValueError("wall_seconds 必须大于 0")
    successful = [float(value) for value in latencies_ms if value is not None]
    if any(value < 0 for value in successful):
        raise ValueError("延迟不能为负数")

    if successful:
        average = mean(successful)
        deviation = stdev(successful) if len(successful) > 1 else 0.0
        margin = 1.96 * deviation / math.sqrt(len(successful)) if len(successful) > 1 else 0.0
        latency: dict[str, object] = {
            "p50": _percentile(successful, 0.50),
            "p95": _percentile(successful, 0.95),
            "mean": average,
            "stddev": deviation,
            "ci95": [average - margin, average + margin],
        }
    else:
        latency = {"p50": None, "p95": None, "mean": None, "stddev": None, "ci95": [None, None]}

    return {
        "total_runs": len(latencies_ms),
        "successful_runs": len(successful),
        "success_rate": len(successful) / len(latencies_ms),
        "throughput_per_second": len(successful) / wall_seconds,
        "latency_ms": latency,
        "energy": _energy_report(power_samples),
    }
