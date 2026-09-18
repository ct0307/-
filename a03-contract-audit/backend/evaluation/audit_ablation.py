"""V0-V4 证据驱动审查消融比较器。

比较器只接受同一冻结上下文和同一金标准哈希，缺失指标保留为 None，
避免把未测量误报为零。
"""
from __future__ import annotations

import math
from numbers import Real
from typing import Any, Mapping, Sequence


ABLATION_SCOPES = {
    "V0": "baseline",
    "V1": "independent_agents_prompts",
    "V2": "rules",
    "V3": "reranker",
    "V4": "support_v3",
}

METRICS = (
    "risk_precision", "risk_recall", "risk_f1", "high_risk_recall",
    "unsupported_claim_rate", "false_accept_rate", "manual_review_rate",
    "unique_contribution_rate", "claim_correction_rate", "conflict_rate",
    "p50_latency_ms", "p95_latency_ms", "mean_tokens", "success_rate",
)


def _number(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{field} 必须是有限数值或 null")
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError(f"{field} 必须是有限数值或 null")
    return converted


def _delta(current: Mapping[str, Any], previous: Mapping[str, Any] | None) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for metric in METRICS:
        value = current.get(metric)
        if value is None or previous is None or previous.get(metric) is None:
            result[metric] = None
            continue
        result[metric] = _number(value, field=f"overall.{metric}") - _number(
            previous[metric], field=f"overall.{metric}"
        )
    return result


def compare_ablation_runs(runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if len(runs) != 5 or {run.get("version") for run in runs} != set(ABLATION_SCOPES):
        raise ValueError("消融评测必须包含完整 V0-V4")
    ordered = sorted(runs, key=lambda run: str(run["version"]))
    ordered = [next(run for run in ordered if run["version"] == f"V{i}") for i in range(5)]
    contexts = [run.get("frozen_context") for run in ordered]
    gold_hashes = [run.get("input_hashes", {}).get("gold_sha256") for run in ordered]
    if any(context != contexts[0] for context in contexts[1:]) or len(set(gold_hashes)) != 1:
        raise ValueError("V0-V4 必须使用同一冻结上下文和金标准")
    if not isinstance(gold_hashes[0], str) or len(gold_hashes[0]) != 64:
        raise ValueError("gold_sha256 必须是 64 位哈希")
    for run in ordered:
        if not isinstance(run.get("overall"), Mapping):
            raise ValueError(f"{run['version']}.overall 必须是对象")
        for metric, value in run["overall"].items():
            if value is not None:
                _number(value, field=f"{run['version']}.overall.{metric}")
    baseline = ordered[0]["overall"]
    rows = []
    for index, run in enumerate(ordered):
        overall = run["overall"]
        rows.append({
            "version": run["version"],
            "scope": ABLATION_SCOPES[run["version"]],
            "overall": dict(overall),
            "component_versions": dict(run.get("component_versions") or {}),
            "delta_previous": _delta(overall, ordered[index - 1]["overall"] if index else None),
            "delta_v0": _delta(overall, baseline if index else None),
        })
    return {"gold_sha256": gold_hashes[0], "frozen_context": contexts[0], "runs": rows}


def render_ablation_markdown(result: Mapping[str, Any]) -> str:
    lines = ["# V0-V4 审查消融结果", "", f"- 金标准哈希：`{result['gold_sha256']}`", ""]
    lines.append("| 版本 | 范围 | 风险 F1 | 高风险召回 | 错误自动接受率 | P95 延迟 |")
    lines.append("|---|---|---:|---:|---:|---:|")
    for row in result["runs"]:
        overall = row["overall"]
        values = [overall.get(key) for key in ("risk_f1", "high_risk_recall", "false_accept_rate", "p95_latency_ms")]
        display = ["未测量" if value is None else str(value) for value in values]
        lines.append(f"| {row['version']} | {row['scope']} | " + " | ".join(display) + " |")
    lines.extend(["", "缺少真实金标、模型或设备证据的指标保持‘未测量’，不解释为零或达标。", ""])
    return "\n".join(lines)
