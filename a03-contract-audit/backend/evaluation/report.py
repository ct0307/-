"""从版本化原始证据生成不可误报的 Markdown 报告。"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from evaluation.evidence import RUN_STATUSES, SCHEMA_VERSION


_STREAMS = {
    "elements": "elements.jsonl",
    "batch": "batch-events.jsonl",
    "benchmark": "benchmark.jsonl",
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class InvalidEvidence(ValueError):
    """证据缺失、被篡改或内部矛盾。"""


@dataclass(frozen=True)
class ReportResult:
    status: str
    path: Path


def aggregate_status(statuses: Mapping[str, str]) -> str:
    if not statuses:
        raise InvalidEvidence("manifest.modules 不能为空")
    unknown = set(statuses.values()) - RUN_STATUSES
    if unknown:
        raise InvalidEvidence(f"未知模块状态: {sorted(unknown)}")
    for status in ("error", "failed", "blocked", "passed"):
        if status in statuses.values():
            return status
    raise InvalidEvidence("无法聚合模块状态")


def _load_manifest(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise InvalidEvidence("缺少 manifest.json") from exc
    except json.JSONDecodeError as exc:
        raise InvalidEvidence("manifest.json 不是有效 JSON") from exc
    if not isinstance(manifest, dict):
        raise InvalidEvidence("manifest.json 必须是对象")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise InvalidEvidence("manifest schema_version 不受支持")
    run_id = manifest.get("run_id")
    if run_id != run_dir.name:
        raise InvalidEvidence(
            f"manifest run_id 与目录不一致: {run_id!r} != {run_dir.name!r}"
        )
    modules = manifest.get("modules")
    if not isinstance(modules, dict) or any(
        not isinstance(name, str) or not isinstance(status, str)
        for name, status in modules.items()
    ):
        raise InvalidEvidence("manifest.modules 必须是状态对象")
    unknown_modules = set(modules) - set(_STREAMS)
    if unknown_modules:
        raise InvalidEvidence(f"未知证据模块: {sorted(unknown_modules)}")
    expected_status = aggregate_status(modules)
    if manifest.get("status") != expected_status:
        raise InvalidEvidence(
            f"manifest 状态与模块状态矛盾: {manifest.get('status')} != {expected_status}"
        )
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict):
        raise InvalidEvidence("manifest.inputs 必须是对象")
    for key, value in inputs.items():
        if key.endswith("_sha256") and (
            not isinstance(value, str) or not _SHA256.fullmatch(value)
        ):
            raise InvalidEvidence(f"manifest.inputs.{key} 不是有效 SHA-256")
    return manifest


def _load_events(path: Path, run_id: str) -> list[dict[str, Any]]:
    if not path.is_file():
        raise InvalidEvidence(f"缺少 {path.name}")
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise InvalidEvidence(f"{path.name}:{line_number} 不是有效 JSON") from exc
        if not isinstance(event, dict):
            raise InvalidEvidence(f"{path.name}:{line_number} 必须是对象")
        if event.get("schema_version") != SCHEMA_VERSION:
            raise InvalidEvidence(f"{path.name}:{line_number} schema_version 不一致")
        if event.get("run_id") != run_id:
            raise InvalidEvidence(f"{path.name}:{line_number} run_id 不一致")
        if not isinstance(event.get("payload"), dict):
            raise InvalidEvidence(f"{path.name}:{line_number} payload 必须是对象")
        events.append(event["payload"])
    if not events:
        raise InvalidEvidence(f"{path.name} 没有事件")
    return events


def _events_of(events: Sequence[Mapping[str, Any]], name: str) -> list[Mapping[str, Any]]:
    return [event for event in events if event.get("event") == name]


def _validate_elements(
    status: str,
    inputs: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    if status in {"blocked", "error"}:
        return None
    summaries = _events_of(events, "summary")
    if len(summaries) != 1:
        raise InvalidEvidence("elements 必须且只能包含一个 summary 事件")
    sample_count = inputs.get("sample_count")
    cases = _events_of(events, "case")
    if not isinstance(sample_count, int) or sample_count <= 0:
        raise InvalidEvidence("elements sample_count 必须是正整数")
    if len(cases) != sample_count or summaries[0].get("sample_count") != sample_count:
        raise InvalidEvidence("elements case 事件数量与 sample_count 不一致")
    overall = summaries[0].get("overall")
    if not isinstance(overall, Mapping) or not isinstance(overall.get("f1"), (int, float)):
        raise InvalidEvidence("elements summary 缺少 overall.f1")
    min_f1 = inputs.get("min_f1")
    expected_status = "passed" if overall["f1"] >= min_f1 else "failed"
    if status != expected_status:
        raise InvalidEvidence("elements 状态与 F1 阈值矛盾")
    return summaries[0]


def _validate_batch(
    status: str,
    inputs: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    if status == "blocked":
        if not _events_of(events, "blocked"):
            raise InvalidEvidence("blocked 批测缺少 blocked 事件")
        return None
    if status == "error":
        return None
    if inputs.get("valid_count") != 50 or inputs.get("invalid_count") != 2:
        raise InvalidEvidence("batch manifest 不是 50+2 口径")
    valid_submissions = _events_of(events, "valid_submitted")
    invalid_submissions = _events_of(events, "invalid_submitted")
    summaries = _events_of(events, "summary")
    if len(valid_submissions) != 1 or valid_submissions[0].get("sample_count") != 50:
        raise InvalidEvidence("batch 缺少 50 文件同批提交证据")
    if len(invalid_submissions) != 2:
        raise InvalidEvidence("batch 异常样本隔离事件必须为 2 个")
    if len(summaries) != 1 or summaries[0].get("status") != status:
        raise InvalidEvidence("batch summary 与模块状态不一致")
    if status == "passed":
        done_states = [
            event
            for event in _events_of(events, "batch_state")
            if event.get("status") == "done"
            and event.get("total") == 50
            and event.get("completed") == 50
            and event.get("failed") == 0
        ]
        if len(done_states) < 2:
            raise InvalidEvidence("batch 缺少完成终态及刷新恢复证据")
    return summaries[0]


def _validate_benchmark(
    status: str,
    inputs: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    if status == "blocked":
        if not _events_of(events, "blocked"):
            raise InvalidEvidence("blocked 基准缺少 blocked 事件")
        return None
    if status == "error":
        return None
    case_count = inputs.get("case_count")
    warmup_runs = inputs.get("warmup_runs")
    measured_runs = inputs.get("measured_runs")
    if not isinstance(case_count, int) or case_count <= 0:
        raise InvalidEvidence("benchmark case_count 必须是正整数")
    if warmup_runs != 3 or measured_runs != 5:
        raise InvalidEvidence("benchmark 必须是 3+5 轮次")
    invocations = _events_of(events, "invocation")
    expected_count = 2 * case_count * (warmup_runs + measured_runs)
    if len(invocations) != expected_count:
        raise InvalidEvidence(
            f"benchmark invocation 数量应为 {expected_count}，实际为 {len(invocations)}"
        )
    summaries = _events_of(events, "target_summary")
    comparisons = _events_of(events, "comparison")
    if len(summaries) != 2 or {item.get("target") for item in summaries} != {
        "openclaw",
        "gpu",
    }:
        raise InvalidEvidence("benchmark 必须包含两个目标汇总")
    if len(comparisons) != 1 or comparisons[0].get("status") != status:
        raise InvalidEvidence("benchmark comparison 与模块状态不一致")
    return comparisons[0]


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _render_report(
    manifest: Mapping[str, Any],
    summaries: Mapping[str, Mapping[str, Any] | None],
) -> str:
    lines = [
        "# 硬指标证据报告",
        "",
        f"- Run ID：`{manifest['run_id']}`",
        f"- 状态：`{manifest['status']}`",
        f"- Git 提交：`{manifest.get('git_commit', 'unknown')}`",
        f"- 工作区有未提交改动：`{manifest.get('git_dirty', True)}`",
        "",
        "## 模块状态",
        "",
        "| 模块 | 状态 |",
        "|---|---|",
    ]
    for module, status in manifest["modules"].items():
        lines.append(f"| {module} | `{status}` |")
    lines.extend(["", "## 输入绑定", "", "| 项目 | 值 |", "|---|---|"])
    for key, value in sorted(manifest["inputs"].items()):
        lines.append(f"| {key} | `{_format_value(value)}` |")

    elements = summaries.get("elements")
    if elements is not None:
        overall = elements["overall"]
        lines.extend(
            [
                "",
                "## 要素评测",
                "",
                f"- 样本数：{elements['sample_count']}",
                f"- Precision：{_format_value(overall.get('precision'))}",
                f"- Recall：{_format_value(overall.get('recall'))}",
                f"- F1：{_format_value(overall.get('f1'))}",
                f"- 错误字段数：{elements.get('error_count')}",
            ]
        )
    batch = summaries.get("batch")
    if batch is not None:
        lines.extend(
            [
                "",
                "## 批量验收",
                "",
                f"- 有效样本：{batch.get('valid_count')}",
                f"- 异常样本：{batch.get('invalid_count')}",
                f"- 批次 ID：{batch.get('valid_batch_id')}",
            ]
        )
    benchmark = summaries.get("benchmark")
    if benchmark is not None:
        lines.extend(
            [
                "",
                "## 算力对比",
                "",
                f"- OpenClaw 成功率：{_format_value(benchmark.get('openclaw_success_rate'))}",
                f"- GPU 成功率：{_format_value(benchmark.get('gpu_success_rate'))}",
                f"- OpenClaw P95：{_format_value(benchmark.get('openclaw_p95'))}",
                f"- GPU P95：{_format_value(benchmark.get('gpu_p95'))}",
            ]
        )
    lines.extend(
        [
            "",
            "## 证据边界",
            "",
            "报告仅汇总版本化指标、运行状态和输入哈希，不包含合同正文、认证信息、提示词或模型响应正文。",
            "",
        ]
    )
    return "\n".join(lines)


def build_report(run_dir: Path) -> ReportResult:
    run_dir = run_dir.resolve()
    manifest = _load_manifest(run_dir)
    summaries: dict[str, Mapping[str, Any] | None] = {}
    validators = {
        "elements": _validate_elements,
        "batch": _validate_batch,
        "benchmark": _validate_benchmark,
    }
    for module, status in manifest["modules"].items():
        events = _load_events(run_dir / _STREAMS[module], manifest["run_id"])
        summaries[module] = validators[module](status, manifest["inputs"], events)

    report_path = run_dir / "report.md"
    temporary_path = run_dir / "report.md.tmp"
    temporary_path.write_text(_render_report(manifest, summaries), encoding="utf-8")
    temporary_path.replace(report_path)
    return ReportResult(status=manifest["status"], path=report_path)
