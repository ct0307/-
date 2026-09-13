"""从版本化原始证据生成不可误报的 Markdown 报告。"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from evaluation.audit_comparison import (
    QUALITY_THRESHOLDS,
    compare_audit_candidates,
    quality_gate_failures,
)
from evaluation.audit_quality import summarize_audit_cases
from evaluation.evidence import RUN_STATUSES, SCHEMA_VERSION
from evaluation.snapshot import (
    MAX_FILE_BYTES,
    MAX_JSONL_LINE_BYTES,
    MAX_JSONL_LINES,
    JsonObjectSnapshot,
    read_json_object_snapshot,
    read_jsonl_snapshot,
)


_STREAMS = {
    "elements": "elements.jsonl",
    "evidence": "evidence.jsonl",
    "retrieval": "retrieval.jsonl",
    "batch": "batch-events.jsonl",
    "benchmark": "benchmark.jsonl",
    "audit": "audit.jsonl",
    "audit_comparison": "audit-comparison.jsonl",
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_EVENT_BYTES = MAX_FILE_BYTES
MAX_EVENT_LINES = MAX_JSONL_LINES
MAX_EVENT_LINE_BYTES = MAX_JSONL_LINE_BYTES


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
        manifest = read_json_object_snapshot(
            path, "manifest.json", max_bytes=MAX_MANIFEST_BYTES
        ).value
    except FileNotFoundError as exc:
        raise InvalidEvidence("缺少 manifest.json") from exc
    except (OSError, ValueError) as exc:
        raise InvalidEvidence(f"manifest.json 无效: {exc}") from exc
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
        if not key.endswith("_sha256"):
            continue
        if isinstance(value, str) and _SHA256.fullmatch(value):
            continue
        if isinstance(value, Mapping) and value and all(
            isinstance(name, str)
            and bool(name)
            and isinstance(digest, str)
            and bool(_SHA256.fullmatch(digest))
            for name, digest in value.items()
        ):
            continue
        raise InvalidEvidence(f"manifest.inputs.{key} 不是有效 SHA-256 或哈希对象")
    return manifest


def _load_events(path: Path, run_id: str) -> list[dict[str, Any]]:
    if not path.is_file():
        raise InvalidEvidence(f"缺少 {path.name}")
    try:
        records, _sha256 = read_jsonl_snapshot(
            path,
            path.name,
            max_bytes=MAX_EVENT_BYTES,
            max_lines=MAX_EVENT_LINES,
            max_line_bytes=MAX_EVENT_LINE_BYTES,
        )
    except (OSError, ValueError) as exc:
        raise InvalidEvidence(f"{path.name} 无效: {exc}") from exc
    events: list[dict[str, Any]] = []
    for line_number, event in enumerate(records, 1):
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


def _validate_evidence(
    status: str,
    inputs: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    if status in {"blocked", "error"}:
        return None
    summaries = _events_of(events, "summary")
    cases = _events_of(events, "case")
    sample_count = inputs.get("sample_count")
    if len(summaries) != 1:
        raise InvalidEvidence("evidence 必须且只能包含一个 summary 事件")
    if not isinstance(sample_count, int) or sample_count <= 0:
        raise InvalidEvidence("evidence sample_count 必须是正整数")
    if len(cases) != sample_count or summaries[0].get("sample_count") != sample_count:
        raise InvalidEvidence("evidence case 事件数量与 sample_count 不一致")
    overall = summaries[0].get("overall")
    if not isinstance(overall, Mapping) or not isinstance(overall.get("macro_f1"), (int, float)):
        raise InvalidEvidence("evidence summary 缺少 overall.macro_f1")
    min_f1 = inputs.get("min_f1")
    expected_status = "passed" if overall["macro_f1"] >= min_f1 else "failed"
    if status != expected_status:
        raise InvalidEvidence("evidence 状态与宏平均 F1 阈值矛盾")
    return summaries[0]


def _validate_retrieval(
    status: str,
    inputs: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    if status in {"blocked", "error"}:
        return None
    summaries = _events_of(events, "summary")
    cases = _events_of(events, "case")
    sample_count = inputs.get("sample_count")
    k = inputs.get("k")
    min_recall = inputs.get("min_recall")
    if len(summaries) != 1:
        raise InvalidEvidence("retrieval 必须且只能包含一个 summary 事件")
    if not isinstance(sample_count, int) or sample_count <= 0 or len(cases) != sample_count:
        raise InvalidEvidence("retrieval case 事件数量与 sample_count 不一致")
    recall_key = f"recall@{k}"
    overall = summaries[0].get("overall")
    if not isinstance(overall, Mapping) or not isinstance(overall.get(recall_key), (int, float)):
        raise InvalidEvidence(f"retrieval summary 缺少 {recall_key}")
    expected_status = "passed" if overall[recall_key] >= min_recall else "failed"
    if status != expected_status:
        raise InvalidEvidence("retrieval 状态与 Recall 阈值矛盾")
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


def _validate_audit(
    status: str,
    inputs: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    if status in {"blocked", "error"}:
        return None
    summaries = _events_of(events, "summary")
    cases = _events_of(events, "case")
    if len(summaries) != 1:
        raise InvalidEvidence("audit 必须且只能包含一个 summary 事件")
    summary = summaries[0]
    sample_count = inputs.get("sample_count")
    if (
        not isinstance(sample_count, int)
        or isinstance(sample_count, bool)
        or sample_count <= 0
        or len(cases) != sample_count
        or summary.get("sample_count") != sample_count
    ):
        raise InvalidEvidence("audit case 事件数量与 sample_count 不一致")
    basis = inputs.get("evaluation_basis")
    if basis not in {"synthetic", "human_gold"} or summary.get("evaluation_basis") != basis:
        raise InvalidEvidence("audit evaluation_basis 不一致")
    input_hashes = summary.get("input_hashes")
    if not isinstance(input_hashes, Mapping) or input_hashes != {
        "gold_sha256": inputs.get("gold_sha256"),
        "predictions_sha256": inputs.get("predictions_sha256"),
    }:
        raise InvalidEvidence("audit summary 输入哈希与 manifest 不一致")
    try:
        derived = summarize_audit_cases(cases)
        failures = quality_gate_failures(derived["overall"])
    except ValueError as exc:
        raise InvalidEvidence(f"audit case 事件无效: {exc}") from exc
    expected_summary: dict[str, Any] = {
        "event": "summary",
        "sample_count": sample_count,
        "evaluation_basis": basis,
        "input_hashes": dict(input_hashes),
        "overall": derived["overall"],
        "cost_evidence_complete": derived["cost_evidence_complete"],
        "cost_metadata": derived["cost_metadata"],
        "quality_gate_failures": failures,
    }
    if "experiment" in derived:
        expected_summary["experiment"] = derived["experiment"]
    if dict(summary) != expected_summary:
        raise InvalidEvidence("audit summary 与 case 事实源重算结果不一致")
    expected_status = "passed" if not failures else "failed"
    if status != expected_status:
        raise InvalidEvidence("audit 模块状态与质量门槛结果不一致")
    return summary


def load_validated_audit_summary(
    summary_path: Path,
    *,
    summary_snapshot: JsonObjectSnapshot | None = None,
) -> dict[str, Any]:
    """加载并验证 audit-quality 的 manifest、事件流与汇总文件。"""
    summary_path = Path(summary_path)
    if summary_path.name != "audit-summary.json":
        raise InvalidEvidence("候选文件名必须是 audit-summary.json")
    snapshot = summary_snapshot or read_json_object_snapshot(summary_path, "审计候选汇总")
    run_dir = summary_path.parent
    manifest = _load_manifest(run_dir)
    if manifest.get("command") != "audit-quality" or set(manifest["modules"]) != {"audit"}:
        raise InvalidEvidence("候选目录必须是单一 audit-quality 运行产物")
    status = manifest["modules"]["audit"]
    events = _load_events(run_dir / _STREAMS["audit"], str(manifest["run_id"]))
    validated = _validate_audit(status, manifest["inputs"], events)
    if validated is None:
        raise InvalidEvidence("候选审计运行没有可比较汇总")
    expected_file = {key: value for key, value in validated.items() if key != "event"}
    expected_file["cases"] = [
        {key: value for key, value in case.items() if key != "event"}
        for case in _events_of(events, "case")
    ]
    if snapshot.value != expected_file:
        raise InvalidEvidence("audit-summary.json 与 manifest 或 audit.jsonl 不一致")
    return dict(snapshot.value)


def _validate_audit_comparison(
    status: str,
    inputs: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    summaries = _events_of(events, "summary")
    candidate_events = _events_of(events, "candidate")
    if len(summaries) != 1:
        raise InvalidEvidence("audit_comparison 必须且只能包含一个 summary")
    summary = summaries[0]
    count = inputs.get("candidate_count")
    names = inputs.get("candidate_names")
    candidate_inputs = inputs.get("candidate_inputs")
    if (
        not isinstance(names, list)
        or not all(isinstance(name, str) and name for name in names)
    ):
        raise InvalidEvidence("audit_comparison manifest 候选集不一致")
    if (
        not isinstance(count, int)
        or isinstance(count, bool)
        or count <= 0
        or len(names) != count
        or not isinstance(candidate_inputs, list)
        or len(candidate_inputs) != count
        or len(candidate_events) != count
    ):
        raise InvalidEvidence("audit_comparison manifest 候选集不一致")
    expected_bindings: list[dict[str, Any]] = []
    for position, binding in enumerate(candidate_inputs):
        if (
            not isinstance(binding, Mapping)
            or binding.get("position") != position
            or binding.get("candidate") != names[position]
            or not isinstance(binding.get("input_sha256"), str)
            or not _SHA256.fullmatch(binding["input_sha256"])
            or not isinstance(binding.get("sample_count"), int)
            or isinstance(binding.get("sample_count"), bool)
            or binding["sample_count"] <= 0
        ):
            raise InvalidEvidence("audit_comparison manifest 候选绑定无效")
        expected_bindings.append(dict(binding))
    event_bindings = [
        {
            "position": event.get("position"),
            "candidate": event.get("candidate"),
            "input_sha256": event.get("input_sha256"),
            "sample_count": event.get("sample_count"),
        }
        for event in candidate_events
    ]
    if event_bindings != expected_bindings:
        raise InvalidEvidence("audit_comparison 候选哈希或样本数与 manifest 不一致")

    expected_thresholds = {
        metric: {"operator": operator, "value": threshold}
        for metric, (operator, threshold) in QUALITY_THRESHOLDS.items()
    }
    if summary.get("thresholds") != expected_thresholds:
        raise InvalidEvidence("audit_comparison 不是固定八项质量门槛")
    comparison_status = summary.get("status")
    if inputs.get("evaluation_basis") != summary.get("evaluation_basis"):
        raise InvalidEvidence("audit_comparison evaluation_basis 与 manifest 不一致")
    expected_manifest_status = {
        "passed": "passed",
        "failed": "failed",
        "quality_passed_cost_inconclusive": "blocked",
    }.get(comparison_status)
    if expected_manifest_status is None or status != expected_manifest_status:
        raise InvalidEvidence("audit_comparison 状态与比较结果不一致")
    quality_passed = summary.get("quality_passed")
    rejected = summary.get("rejected")
    ranking = summary.get("ranking")
    selected = summary.get("selected")
    inconclusive = summary.get("cost_inconclusive")
    if (
        not isinstance(quality_passed, list)
        or not all(isinstance(name, str) for name in quality_passed)
        or not isinstance(rejected, Mapping)
        or not all(
            isinstance(name, str)
            and isinstance(failures, list)
            and all(isinstance(metric, str) for metric in failures)
            for name, failures in rejected.items()
        )
        or not isinstance(ranking, list)
        or not all(isinstance(name, str) for name in ranking)
        or not isinstance(inconclusive, list)
        or not all(isinstance(name, str) for name in inconclusive)
        or set(quality_passed) | set(rejected) != set(names)
        or set(quality_passed) & set(rejected)
    ):
        raise InvalidEvidence("audit_comparison 候选门槛分组不一致")
    if comparison_status == "passed":
        if not ranking or ranking != list(dict.fromkeys(ranking)):
            raise InvalidEvidence("audit_comparison ranking 无效")
        if set(ranking) != set(quality_passed):
            raise InvalidEvidence("audit_comparison ranking 与质量通过集不一致")
        if selected != ranking[0]:
            raise InvalidEvidence("audit_comparison selected 与 ranking 第一名不一致")
        if inconclusive:
            raise InvalidEvidence("audit_comparison 已选中时不得存在成本证据不足项")
    elif selected is not None or ranking:
        raise InvalidEvidence("audit_comparison 未通过时 selected 必须为 null 且 ranking 为空")
    if comparison_status == "failed" and quality_passed:
        raise InvalidEvidence("audit_comparison failed 与质量通过集矛盾")
    if comparison_status == "quality_passed_cost_inconclusive" and (
        not quality_passed or not inconclusive or not set(inconclusive) <= set(quality_passed)
    ):
        raise InvalidEvidence("audit_comparison 成本证据不足集无效")
    reconstructed = [
        {
            key: value
            for key, value in event.items()
            if key not in {"event", "input_sha256", "position"}
        }
        for event in candidate_events
    ]
    try:
        expected = compare_audit_candidates(reconstructed).to_dict()
    except ValueError as exc:
        raise InvalidEvidence(f"audit_comparison 候选证据无效: {exc}") from exc
    if dict(summary) != {"event": "summary", **expected}:
        raise InvalidEvidence(
            "audit_comparison 门槛、排序或 selected 与候选原始指标不一致"
        )
    return summary


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
    evidence = summaries.get("evidence")
    if evidence is not None:
        overall = evidence["overall"]
        lines.extend(
            [
                "",
                "## 依据支持关系评测",
                "",
                f"- 合同样本数：{evidence.get('sample_count')}",
                f"- 风险条数：{evidence.get('risk_count')}",
                f"- Accuracy：{_format_value(overall.get('accuracy'))}",
                f"- Macro F1：{_format_value(overall.get('macro_f1'))}",
                f"- 缺失预测：{evidence.get('missing_prediction_count')}",
            ]
        )
    retrieval = summaries.get("retrieval")
    if retrieval is not None:
        overall = retrieval["overall"]
        lines.extend(
            [
                "",
                "## RAG 检索评测",
                "",
                f"- 样本数：{retrieval.get('sample_count')}",
                *[
                    f"- {name.replace('recall', 'Recall').replace('precision', 'Precision').replace('ndcg', 'nDCG').replace('mrr', 'MRR')}：{_format_value(value)}"
                    for name, value in overall.items()
                ],
                f"- 缺失预测：{retrieval.get('missing_prediction_count')}",
            ]
        )
    audit = summaries.get("audit")
    if audit is not None:
        overall = audit["overall"]
        evaluation_label = (
            "人工金标准评测"
            if audit.get("evaluation_basis") == "human_gold"
            else "合成数据技术预评测"
        )
        lines.extend(
            [
                "",
                f"## 合同审查{evaluation_label}",
                "",
                f"- 样本数：{audit.get('sample_count')}",
                f"- 高风险召回率：{_format_value(overall.get('high_risk_recall'))}",
                f"- 整体风险召回率：{_format_value(overall.get('risk_recall'))}",
                f"- 风险精确率：{_format_value(overall.get('risk_precision'))}",
                f"- 错误成功率：{_format_value(overall.get('false_success_rate'))}",
                f"- 最终截断率：{_format_value(overall.get('final_truncation_rate'))}",
                f"- 质量门槛失败项：{', '.join(audit.get('quality_gate_failures', [])) or '无'}",
            ]
        )
        if audit.get("evaluation_basis") == "synthetic":
            lines.append("- 边界：本结果仅是合成数据技术预评测，不代表人工准确率结论。")
    comparison = summaries.get("audit_comparison")
    if comparison is not None:
        basis = comparison.get("evaluation_basis")
        title = (
            "合同审查合成数据技术预评测对比"
            if basis == "synthetic"
            else "合同审查人工金标准质量与成本对比"
            if basis == "human_gold"
            else "合同审查质量与成本对比"
        )
        lines.extend(["", f"## {title}", ""])
        comparison_status = comparison.get("status")
        if comparison_status == "passed":
            lines.append(f"- 选中候选：`{comparison.get('selected')}`")
            if basis == "synthetic":
                lines.extend(
                    [
                        "- 结论：该候选仅在本次冻结模型、合成数据集和环境的技术预评测范围内成本排序第一。",
                        "- 边界：该结果不代表人工准确率、真实合同效果或生产环境最优性价比结论。",
                    ]
                )
            else:
                lines.append(
                    "- 结论：该候选仅在本次冻结模型、数据集和环境下最具性价比。"
                )
        elif comparison_status == "quality_passed_cost_inconclusive":
            lines.append("- 结论：质量门槛已通过，但成本证据不足，不选出最具性价比候选。")
        else:
            lines.append("- 结论：无候选通过全部质量门槛。")
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
        "evidence": _validate_evidence,
        "retrieval": _validate_retrieval,
        "batch": _validate_batch,
        "benchmark": _validate_benchmark,
        "audit": _validate_audit,
        "audit_comparison": _validate_audit_comparison,
    }
    for module, status in manifest["modules"].items():
        events = _load_events(run_dir / _STREAMS[module], manifest["run_id"])
        summaries[module] = validators[module](status, manifest["inputs"], events)

    report_path = run_dir / "report.md"
    temporary_path = run_dir / "report.md.tmp"
    temporary_path.write_text(_render_report(manifest, summaries), encoding="utf-8")
    temporary_path.replace(report_path)
    return ReportResult(status=manifest["status"], path=report_path)
