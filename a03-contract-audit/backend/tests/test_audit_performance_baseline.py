"""离线性能基线的完整性与脱敏边界。"""
import json

import pytest

from evaluation.audit_performance import compare_runs, render_markdown


def _metrics(samples):
    run = {"samples": samples}
    return compare_runs(run, run).speed.baseline


def test_success_rate_counts_manual_review_separately():
    metrics = _metrics([
        {"status": "done"}, {"status": "review_required"},
        {"status": "audit_failed"}, {"status": "failed"},
    ])
    assert metrics.success_count == 1
    assert metrics.success_rate == 0.25
    assert metrics.review_required_count == 1


@pytest.mark.parametrize("samples", [[], [{}], [{"status": "done"}, {}], [{"status": "reviewing"}]])
def test_incomplete_terminal_status_does_not_invent_success_rate(samples):
    metrics = _metrics(samples)
    assert metrics.success_count is None
    assert metrics.success_rate is None
    assert metrics.review_required_count is None


def test_runner_flat_timings_and_nested_timings_share_phase_statistics():
    metrics = _metrics([
        {"parse_ms": 100, "legal_agent_ms": 400},
        {"timings": {"parse_ms": 300, "legal_agent_ms": 800}},
    ])
    assert metrics.phase_ms["parse_ms"] == 200
    assert metrics.phase_p50_ms["parse_ms"] == 200
    assert metrics.phase_p95_ms["parse_ms"] == 290
    assert metrics.phase_sample_counts["parse_ms"] == 2
    assert metrics.phase_ms["persist_ms"] is None
    assert metrics.phase_sample_counts["persist_ms"] == 0


def test_partial_phases_and_null_metrics_remain_unavailable():
    run = {"samples": [
        {"total_ms": None, "fallback_count": None, "timings": {"parse_ms": 100}, "llm_calls": [{"latency_ms": None}]},
        {"total_ms": 200, "timings": {}, "llm_calls": []},
    ]}
    report = compare_runs(run, run)
    metrics = report.speed.baseline
    assert metrics.total_ms is None
    assert metrics.llm_calls == 1
    assert metrics.llm_latency_p50_ms is None
    assert metrics.phase_ms["parse_ms"] is None
    assert metrics.phase_p95_ms["parse_ms"] is None
    assert metrics.phase_sample_counts["parse_ms"] == 1
    assert "baseline.phase_ms.parse_ms" in report.unavailable_metrics
    assert "baseline.success_rate" in report.unavailable_metrics
    assert "baseline.llm_latency_p95_ms" in report.unavailable_metrics


@pytest.mark.parametrize("field", ["latency_ms", "parse_ms"])
@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True, "100"])
def test_invalid_latency_is_rejected_instead_of_dropped(field, value):
    sample = {"llm_calls": [{"latency_ms": value}]} if field == "latency_ms" else {"timings": {"parse_ms": value}}
    with pytest.raises(ValueError):
        _metrics([sample])


def test_partial_call_lists_still_validate_present_calls():
    with pytest.raises(ValueError, match="llm_calls"):
        _metrics([{"llm_calls": ["敏感原文"]}, {}])


def test_markdown_exposes_phase_percentiles_and_missing_status_without_source_text():
    run = {"samples": [{"timings": {"parse_ms": 10}, "contract_text": "机密合同", "api_key": "机密密钥"}]}
    report = compare_runs(run, run)
    markdown = render_markdown(report)
    assert "成功率" in markdown
    assert "阶段" in markdown and "parse_ms" in markdown and "P95" in markdown
    assert "不可用" in markdown
    payload = json.dumps(report.to_dict(), ensure_ascii=False)
    assert "机密合同" not in payload + markdown
    assert "机密密钥" not in payload + markdown


def test_null_safety_counter_is_unknown_and_does_not_hide_known_violation():
    run = {"samples": [
        {"unauthorized_evidence_count": None, "unverified_auto_publish_count": None},
        {"unauthorized_evidence_count": 1, "unverified_auto_publish_count": 0},
    ]}
    report = compare_runs(run, run)
    assert report.quality.candidate.unauthorized_evidence_count is None
    assert report.quality.gate_passed is False


def test_cli_reports_offline_baseline_without_model_or_database_access(tmp_path, monkeypatch):
    from evaluation.cli import EXIT_BLOCKED, main
    import socket

    def forbid_network(*args, **kwargs):
        raise AssertionError("离线性能分析不应连接网络")

    monkeypatch.setattr(socket.socket, "connect", forbid_network)
    source = tmp_path / "redacted.jsonl"
    source.write_text(json.dumps({
        "case_id": "synthetic-1", "status": "done", "total_ms": 120,
        "parse_ms": 10, "llm_calls": [{"latency_ms": 80}],
        "contract_text": "机密合同", "api_key": "机密密钥",
    }), encoding="utf-8")
    output_json = tmp_path / "baseline.json"
    output_markdown = tmp_path / "baseline.md"
    assert main([
        "audit-performance", "--baseline", str(source), "--candidate", str(source),
        "--json-output", str(output_json), "--markdown-output", str(output_markdown),
    ]) == EXIT_BLOCKED
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["speed"]["baseline"]["success_rate"] == 1
    assert payload["speed"]["baseline"]["phase_p95_ms"]["parse_ms"] == 10
    assert payload["quality"]["gate_passed"] is None
    assert "机密" not in output_json.read_text(encoding="utf-8")
    assert "机密" not in output_markdown.read_text(encoding="utf-8")
