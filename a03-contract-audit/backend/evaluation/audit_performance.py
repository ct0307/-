"""基于脱敏运行摘要的审查性能与质量对比。"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RunSpeedMetrics:
    sample_count: int
    total_ms: int | None
    phase_ms: dict[str, float]
    llm_calls: int | None
    llm_latency_p50_ms: float | None
    llm_latency_p95_ms: float | None
    parse_cache_hits: int | None
    fallback_count: int | None


@dataclass(frozen=True)
class SpeedComparison:
    baseline: RunSpeedMetrics
    candidate: RunSpeedMetrics
    total_ms_delta: int | None
    llm_calls_delta: int | None


@dataclass(frozen=True)
class RunQualityMetrics:
    published_risk_count: int | None
    risk_level_counts: dict[str, int] | None
    evidence_status_counts: dict[str, int] | None
    manual_review_count: int | None
    unauthorized_evidence_count: int | None
    unverified_auto_publish_count: int | None


@dataclass(frozen=True)
class QualityComparison:
    baseline: RunQualityMetrics
    candidate: RunQualityMetrics
    unauthorized_evidence_count: int | None
    unverified_auto_publish_count: int | None
    gate_passed: bool | None


@dataclass(frozen=True)
class AuditPerformanceReport:
    baseline_name: str
    candidate_name: str
    speed: SpeedComparison
    quality: QualityComparison
    unavailable_metrics: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _samples(run: dict[str, Any]) -> list[dict[str, Any]]:
    samples = run.get("samples")
    if not isinstance(samples, list) or not all(isinstance(item, dict) for item in samples):
        raise ValueError("运行摘要必须包含 samples 对象数组")
    return samples


def _sum_if_complete(samples: list[dict], field: str) -> int | None:
    if not samples or any(field not in sample for sample in samples):
        return None
    values = [sample[field] for sample in samples]
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
        raise ValueError(f"{field} 必须为数值")
    return int(sum(values))


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 3)


def _speed_metrics(samples: list[dict]) -> RunSpeedMetrics:
    call_lists = [sample.get("llm_calls") for sample in samples]
    calls_complete = bool(samples) and all(isinstance(value, list) for value in call_lists)
    calls = [call for value in call_lists if isinstance(value, list) for call in value]
    if calls_complete and not all(isinstance(call, dict) for call in calls):
        raise ValueError("llm_calls 必须为对象数组")
    latencies = [
        float(call["latency_ms"])
        for call in calls
        if isinstance(call.get("latency_ms"), (int, float))
        and not isinstance(call.get("latency_ms"), bool)
    ]
    latency_complete = calls_complete and all("latency_ms" in call for call in calls)

    phase_values: dict[str, list[float]] = {}
    for sample in samples:
        timings = sample.get("timings")
        if not isinstance(timings, dict):
            continue
        for name, value in timings.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                phase_values.setdefault(str(name), []).append(float(value))
    phase_means = {
        name: round(sum(values) / len(values), 3)
        for name, values in sorted(phase_values.items())
        if len(values) == len(samples)
    }
    cache_hits = None
    if samples and all(isinstance(sample.get("parse_cache_hit"), bool) for sample in samples):
        cache_hits = sum(1 for sample in samples if sample["parse_cache_hit"])
    return RunSpeedMetrics(
        sample_count=len(samples),
        total_ms=_sum_if_complete(samples, "total_ms"),
        phase_ms=phase_means,
        llm_calls=len(calls) if calls_complete else None,
        llm_latency_p50_ms=_percentile(latencies, 0.50) if latency_complete else None,
        llm_latency_p95_ms=_percentile(latencies, 0.95) if latency_complete else None,
        parse_cache_hits=cache_hits,
        fallback_count=_sum_if_complete(samples, "fallback_count"),
    )


def _quality_metrics(samples: list[dict]) -> RunQualityMetrics:
    risks_complete = bool(samples) and all(isinstance(sample.get("risks"), list) for sample in samples)
    risks = [risk for sample in samples for risk in sample.get("risks", [])]
    if risks_complete and not all(isinstance(risk, dict) for risk in risks):
        raise ValueError("risks 必须为对象数组")
    level_counts = None
    status_counts = None
    manual_count = None
    if risks_complete:
        level_counts = {}
        status_counts = {}
        for risk in risks:
            if "level" in risk:
                level = str(risk["level"])
                level_counts[level] = level_counts.get(level, 0) + 1
            if "evidence_status" in risk:
                status = str(risk["evidence_status"])
                status_counts[status] = status_counts.get(status, 0) + 1
        if all(isinstance(risk.get("requires_manual_review"), bool) for risk in risks):
            manual_count = sum(1 for risk in risks if risk["requires_manual_review"])
    return RunQualityMetrics(
        published_risk_count=len(risks) if risks_complete else None,
        risk_level_counts=level_counts,
        evidence_status_counts=status_counts,
        manual_review_count=manual_count,
        unauthorized_evidence_count=_sum_if_complete(samples, "unauthorized_evidence_count"),
        unverified_auto_publish_count=_sum_if_complete(samples, "unverified_auto_publish_count"),
    )


def compare_runs(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> AuditPerformanceReport:
    baseline_samples = _samples(baseline)
    candidate_samples = _samples(candidate)
    baseline_speed = _speed_metrics(baseline_samples)
    candidate_speed = _speed_metrics(candidate_samples)
    baseline_quality = _quality_metrics(baseline_samples)
    candidate_quality = _quality_metrics(candidate_samples)

    unavailable: list[str] = []
    for prefix, metrics in (
        ("baseline", baseline_speed),
        ("candidate", candidate_speed),
    ):
        for field in ("total_ms", "llm_calls"):
            if getattr(metrics, field) is None:
                unavailable.append(f"{prefix}.{field}")
    for prefix, metrics in (
        ("baseline", baseline_quality),
        ("candidate", candidate_quality),
    ):
        for field in ("unauthorized_evidence_count", "unverified_auto_publish_count"):
            if getattr(metrics, field) is None:
                unavailable.append(f"{prefix}.{field}")

    total_delta = (
        candidate_speed.total_ms - baseline_speed.total_ms
        if candidate_speed.total_ms is not None and baseline_speed.total_ms is not None
        else None
    )
    call_delta = (
        candidate_speed.llm_calls - baseline_speed.llm_calls
        if candidate_speed.llm_calls is not None and baseline_speed.llm_calls is not None
        else None
    )
    unsafe = candidate_quality.unauthorized_evidence_count
    unverified = candidate_quality.unverified_auto_publish_count
    quality_gate = (
        unsafe == 0 and unverified == 0
        if unsafe is not None and unverified is not None
        else None
    )
    return AuditPerformanceReport(
        baseline_name=str(baseline.get("name") or "baseline"),
        candidate_name=str(candidate.get("name") or "candidate"),
        speed=SpeedComparison(
            baseline=baseline_speed,
            candidate=candidate_speed,
            total_ms_delta=total_delta,
            llm_calls_delta=call_delta,
        ),
        quality=QualityComparison(
            baseline=baseline_quality,
            candidate=candidate_quality,
            unauthorized_evidence_count=unsafe,
            unverified_auto_publish_count=unverified,
            gate_passed=quality_gate,
        ),
        unavailable_metrics=tuple(sorted(unavailable)),
    )


def load_run(path: Path) -> dict[str, Any]:
    if path.suffix.casefold() == ".jsonl":
        samples = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return {"name": path.stem, "samples": samples}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} 必须为 JSON 对象")
    return value


def _display(value: object) -> str:
    return "不可用" if value is None else str(value)


def render_markdown(report: AuditPerformanceReport) -> str:
    return "\n".join([
        "# 合同审查性能与质量对比",
        "",
        "## 性能",
        "",
        "| 指标 | 基线 | 候选 | 差值 |",
        "|---|---:|---:|---:|",
        f"| 总耗时(ms) | {_display(report.speed.baseline.total_ms)} | "
        f"{_display(report.speed.candidate.total_ms)} | {_display(report.speed.total_ms_delta)} |",
        f"| LLM 调用数 | {_display(report.speed.baseline.llm_calls)} | "
        f"{_display(report.speed.candidate.llm_calls)} | {_display(report.speed.llm_calls_delta)} |",
        "",
        "## 质量",
        "",
        "| 指标 | 基线 | 候选 |",
        "|---|---:|---:|",
        f"| 越权证据数 | {_display(report.quality.baseline.unauthorized_evidence_count)} | "
        f"{_display(report.quality.candidate.unauthorized_evidence_count)} |",
        f"| 未复核自动发布数 | {_display(report.quality.baseline.unverified_auto_publish_count)} | "
        f"{_display(report.quality.candidate.unverified_auto_publish_count)} |",
        f"| 质量门禁 |  | {_display(report.quality.gate_passed)} |",
        "",
        "不可用指标：" + ("、".join(report.unavailable_metrics) or "无"),
        "",
    ])
