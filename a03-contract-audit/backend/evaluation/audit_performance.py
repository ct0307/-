"""基于脱敏运行摘要的审查性能与质量对比。"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
from typing import Any


_PHASE_FIELDS = ("parse_ms", "legal_agent_ms", "finance_agent_ms", "grounding_ms", "persist_ms")
_TERMINAL_STATUSES = frozenset({"done", "review_required", "audit_failed", "failed"})


@dataclass(frozen=True)
class RunSpeedMetrics:
    sample_count: int
    total_ms: int | None
    total_latency_p50_ms: float | None
    total_latency_p95_ms: float | None
    phase_ms: dict[str, float | None]
    phase_p50_ms: dict[str, float | None]
    phase_p95_ms: dict[str, float | None]
    phase_sample_counts: dict[str, int]
    success_count: int | None
    success_rate: float | None
    review_required_count: int | None
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
    reasons: tuple[str, ...] = ()
    baseline_business_metrics: dict[str, float] | None = None
    candidate_business_metrics: dict[str, float] | None = None


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
    values = [sample[field] for sample in samples if sample.get(field) is not None]
    if not all(type(value) is int and value >= 0 for value in values):
        raise ValueError(f"{field} 必须为非负整数")
    if not samples or len(values) != len(samples):
        return None
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
    total_ms = _sum_if_complete(samples, "total_ms")
    total_latencies = [sample["total_ms"] for sample in samples] if total_ms is not None else []
    call_lists = [sample.get("llm_calls") for sample in samples]
    if any(value is not None and not isinstance(value, list) for value in call_lists):
        raise ValueError("llm_calls 必须为对象数组")
    calls_complete = bool(samples) and all(isinstance(value, list) for value in call_lists)
    calls = [call for value in call_lists if isinstance(value, list) for call in value]
    if not all(isinstance(call, dict) for call in calls):
        raise ValueError("llm_calls 必须为对象数组")
    latencies = []
    for call in calls:
        value = call.get("latency_ms")
        if value is not None:
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError("latency_ms 必须为非负有限数值")
            latencies.append(float(value))
    latency_complete = calls_complete and len(latencies) == len(calls)

    phase_values: dict[str, list[float]] = {name: [] for name in _PHASE_FIELDS}
    for sample in samples:
        timings = sample.get("timings")
        if timings is not None and not isinstance(timings, dict):
            raise ValueError("timings 必须为对象")
        for name in _PHASE_FIELDS:
            value = (timings or {}).get(name, sample.get(name))
            if value is not None:
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                    raise ValueError(f"{name} 必须为非负有限数值")
                phase_values[name].append(float(value))
    phase_means = {
        name: round(sum(values) / len(values), 3) if values and len(values) == len(samples) else None
        for name, values in phase_values.items()
    }
    phase_p50 = {
        name: _percentile(values, 0.50) if phase_means[name] is not None else None
        for name, values in phase_values.items()
    }
    phase_p95 = {
        name: _percentile(values, 0.95) if phase_means[name] is not None else None
        for name, values in phase_values.items()
    }
    statuses = [sample.get("status") for sample in samples]
    statuses_complete = bool(samples) and all(
        isinstance(status, str) and status in _TERMINAL_STATUSES for status in statuses
    )
    success_count = statuses.count("done") if statuses_complete else None
    cache_hits = None
    if samples and all(isinstance(sample.get("parse_cache_hit"), bool) for sample in samples):
        cache_hits = sum(1 for sample in samples if sample["parse_cache_hit"])
    return RunSpeedMetrics(
        sample_count=len(samples),
        total_ms=total_ms,
        total_latency_p50_ms=_percentile(total_latencies, 0.50),
        total_latency_p95_ms=_percentile(total_latencies, 0.95),
        phase_ms=phase_means,
        phase_p50_ms=phase_p50,
        phase_p95_ms=phase_p95,
        phase_sample_counts={name: len(values) for name, values in phase_values.items()},
        success_count=success_count,
        success_rate=success_count / len(samples) if success_count is not None else None,
        review_required_count=statuses.count("review_required") if statuses_complete else None,
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
    safety_violation = any(
        sample.get(field) is not None and sample[field] > 0
        for sample in candidate_samples
        for field in ("unauthorized_evidence_count", "unverified_auto_publish_count")
    )
    reasons: list[str] = []
    identity_fields = (
        "dataset_sha256", "model", "prompt_sha256", "knowledge_revision",
        "dimensions", "concurrency", "deadline_seconds",
    )
    identities = []
    for prefix, run in (("baseline", baseline), ("candidate", candidate)):
        identity = run.get("identity")
        if not isinstance(identity, dict) or any(
            field not in identity or identity[field] is None for field in identity_fields
        ):
            unavailable.append(f"{prefix}.identity")
            identities.append(None)
        else:
            valid = all(
                isinstance(identity[field], str) and bool(identity[field].strip())
                for field in ("dataset_sha256", "model", "prompt_sha256")
            )
            valid = valid and type(identity["knowledge_revision"]) is int and identity["knowledge_revision"] >= 0
            valid = valid and type(identity["concurrency"]) is int and identity["concurrency"] > 0
            deadline = identity["deadline_seconds"]
            valid = valid and type(deadline) in (int, float) and math.isfinite(deadline) and deadline > 0
            dimensions = identity["dimensions"]
            valid = valid and isinstance(dimensions, list) and bool(dimensions) and all(
                isinstance(dimension, str) and bool(dimension.strip()) for dimension in dimensions
            )
            if not valid:
                unavailable.append(f"{prefix}.identity")
                identities.append(None)
            else:
                identities.append({field: identity[field] for field in identity_fields})
    if all(identity is not None for identity in identities) and identities[0] != identities[1]:
        reasons.append("运行身份不一致，不能据此启用候选配置")
    case_sets = []
    for prefix, samples in (("baseline", baseline_samples), ("candidate", candidate_samples)):
        case_ids = [sample.get("case_id") for sample in samples]
        if not case_ids or any(not isinstance(case_id, str) or not case_id.strip() for case_id in case_ids):
            unavailable.append(f"{prefix}.case_ids")
            case_sets.append(None)
        else:
            if len(set(case_ids)) != len(case_ids):
                reasons.append("样本标识重复，不能比较")
            case_sets.append(set(case_ids))
    if all(cases is not None for cases in case_sets) and case_sets[0] != case_sets[1]:
        reasons.append("基线和候选样本集合不一致")
    quality_fields = (
        "high_risk_recall", "risk_f1", "evidence_support_rate",
        "coverage_rate", "manual_review_rate",
    )
    business_metrics = []
    for prefix, run in (("baseline", baseline), ("candidate", candidate)):
        metrics = run.get("quality_metrics")
        if not isinstance(metrics, dict) or any(field not in metrics for field in quality_fields):
            unavailable.append(f"{prefix}.quality_metrics")
            business_metrics.append(None)
            continue
        for field in quality_fields:
            value = metrics[field]
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{prefix}.quality_metrics.{field} 必须是 0 至 1 的有限数值")
        business_metrics.append({field: metrics[field] for field in quality_fields})
    if all(metrics is not None for metrics in business_metrics):
        before, after = business_metrics
        for field in quality_fields[:-1]:
            if after[field] < before[field]:
                reasons.append(f"质量指标下降：{field}")
        if after["manual_review_rate"] > before["manual_review_rate"]:
            reasons.append("人工复核比例上升，需人工核对后再批准")
    if safety_violation:
        reasons.append("候选存在越权证据或未复核自动发布")
    quality_gate = False if safety_violation else None if unavailable else not reasons
    # 性能观测缺项只影响报告完整性，不改变既有质量门禁的判断条件。
    for prefix, metrics in (("baseline", baseline_speed), ("candidate", candidate_speed)):
        for field in (
            "total_latency_p50_ms", "total_latency_p95_ms", "llm_latency_p50_ms",
            "llm_latency_p95_ms", "success_rate", "parse_cache_hits", "fallback_count",
        ):
            if getattr(metrics, field) is None:
                unavailable.append(f"{prefix}.{field}")
        for name, value in metrics.phase_ms.items():
            if value is None:
                unavailable.append(f"{prefix}.phase_ms.{name}")
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
            reasons=tuple(reasons),
            baseline_business_metrics=business_metrics[0],
            candidate_business_metrics=business_metrics[1],
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
        f"| 单份总耗时 P50(ms) | {_display(report.speed.baseline.total_latency_p50_ms)} | "
        f"{_display(report.speed.candidate.total_latency_p50_ms)} |  |",
        f"| 单份总耗时 P95(ms) | {_display(report.speed.baseline.total_latency_p95_ms)} | "
        f"{_display(report.speed.candidate.total_latency_p95_ms)} |  |",
        f"| LLM 调用数 | {_display(report.speed.baseline.llm_calls)} | "
        f"{_display(report.speed.candidate.llm_calls)} | {_display(report.speed.llm_calls_delta)} |",
        f"| 样本数 | {report.speed.baseline.sample_count} | {report.speed.candidate.sample_count} |  |",
        f"| 自动成功数(done) | {_display(report.speed.baseline.success_count)} | "
        f"{_display(report.speed.candidate.success_count)} |  |",
        f"| 自动成功率 | {_display(report.speed.baseline.success_rate)} | "
        f"{_display(report.speed.candidate.success_rate)} |  |",
        f"| 待人工复核数 | {_display(report.speed.baseline.review_required_count)} | "
        f"{_display(report.speed.candidate.review_required_count)} |  |",
        f"| LLM 延迟 P50(ms) | {_display(report.speed.baseline.llm_latency_p50_ms)} | "
        f"{_display(report.speed.candidate.llm_latency_p50_ms)} |  |",
        f"| LLM 延迟 P95(ms) | {_display(report.speed.baseline.llm_latency_p95_ms)} | "
        f"{_display(report.speed.candidate.llm_latency_p95_ms)} |  |",
        "",
        "## 阶段耗时",
        "",
        "| 运行 | 阶段 | 有效样本/全部样本 | 均值(ms) | P50(ms) | P95(ms) |",
        "|---|---|---:|---:|---:|---:|",
        *[
            f"| {label} | {name} | {metrics.phase_sample_counts[name]}/{metrics.sample_count} | "
            f"{_display(metrics.phase_ms[name])} | {_display(metrics.phase_p50_ms[name])} | "
            f"{_display(metrics.phase_p95_ms[name])} |"
            for label, metrics in (("基线", report.speed.baseline), ("候选", report.speed.candidate))
            for name in _PHASE_FIELDS
        ],
        "",
        "成功率仅覆盖输入样本，done 计为自动成功，review_required 单列；缺失或非终态状态时不可用。",
        "阶段可能并行或相互包含，不应累加为总耗时；本报告不自动证明全链路或质量达标。",
        "",
        "## 质量",
        "",
        "| 指标 | 基线 | 候选 |",
        "|---|---:|---:|",
        *[
            f"| {field} | {_display((report.quality.baseline_business_metrics or {}).get(field))} | "
            f"{_display((report.quality.candidate_business_metrics or {}).get(field))} |"
            for field in ("high_risk_recall", "risk_f1", "evidence_support_rate", "coverage_rate", "manual_review_rate")
        ],
        f"| 越权证据数 | {_display(report.quality.baseline.unauthorized_evidence_count)} | "
        f"{_display(report.quality.candidate.unauthorized_evidence_count)} |",
        f"| 未复核自动发布数 | {_display(report.quality.baseline.unverified_auto_publish_count)} | "
        f"{_display(report.quality.candidate.unverified_auto_publish_count)} |",
        f"| 质量门禁 |  | {_display(report.quality.gate_passed)} |",
        "",
        "不可用指标：" + ("、".join(report.unavailable_metrics) or "无"),
        "门禁原因：" + ("；".join(report.quality.reasons) or "无"),
        "",
    ])
