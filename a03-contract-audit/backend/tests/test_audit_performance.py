import json

from evaluation.audit_performance import compare_runs, render_markdown
from evaluation.cli import EXIT_BLOCKED, EXIT_FAILED, EXIT_OK, main


def _run(name: str, *, calls: int, total_ms: int, unsafe: int = 0) -> dict:
    return {
        "name": name,
        "samples": [
            {
                "case_id": f"{name}-1",
                "total_ms": total_ms,
                "timings": {"parse_ms": 10, "legal_agent_ms": total_ms - 10},
                "llm_calls": [
                    {"latency_ms": 100 + index} for index in range(calls)
                ],
                "parse_cache_hit": name == "candidate",
                "fallback_count": 0,
                "risks": [
                    {
                        "level": "high",
                        "evidence_status": "supported",
                        "requires_manual_review": True,
                    }
                ],
                "unauthorized_evidence_count": unsafe,
                "unverified_auto_publish_count": 0,
                "contract_text": "不得出现在报告中的合同正文",
                "prompt": "不得出现在报告中的提示词",
                "response": "不得出现在报告中的模型原文",
            }
        ],
    }


def test_performance_report_separates_speed_and_quality():
    baseline = _run("baseline", calls=10, total_ms=1000)
    candidate = _run("candidate", calls=2, total_ms=600)

    report = compare_runs(baseline, candidate)

    assert report.speed.llm_calls_delta == -8
    assert report.speed.total_ms_delta == -400
    assert report.quality.unauthorized_evidence_count == 0
    assert report.quality.unverified_auto_publish_count == 0
    assert report.quality.gate_passed is True


def test_missing_metrics_remain_unavailable_instead_of_becoming_zero():
    baseline = {"name": "baseline", "samples": [{"case_id": "b"}]}
    candidate = {"name": "candidate", "samples": [{"case_id": "c"}]}

    report = compare_runs(baseline, candidate)

    assert report.speed.total_ms_delta is None
    assert report.quality.unauthorized_evidence_count is None
    assert report.quality.gate_passed is None
    assert "candidate.unauthorized_evidence_count" in report.unavailable_metrics


def test_report_outputs_are_deterministic_and_exclude_sensitive_fields():
    report = compare_runs(
        _run("baseline", calls=2, total_ms=1000),
        _run("candidate", calls=1, total_ms=500),
    )

    payload = json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True)
    markdown = render_markdown(report)

    for secret in ("合同正文", "提示词", "模型原文"):
        assert secret not in payload
        assert secret not in markdown
    assert "性能" in markdown and "质量" in markdown


def test_quality_gate_fails_on_explicit_unsafe_evidence_count():
    report = compare_runs(
        _run("baseline", calls=2, total_ms=1000),
        _run("candidate", calls=1, total_ms=500, unsafe=1),
    )

    assert report.quality.gate_passed is False


def test_cli_writes_json_and_markdown_and_uses_quality_exit_code(tmp_path):
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    json_output = tmp_path / "comparison.json"
    markdown_output = tmp_path / "comparison.md"
    baseline.write_text(json.dumps(_run("baseline", calls=3, total_ms=1000)), encoding="utf-8")
    candidate.write_text(json.dumps(_run("candidate", calls=1, total_ms=500)), encoding="utf-8")

    code = main([
        "audit-performance",
        "--baseline", str(baseline),
        "--candidate", str(candidate),
        "--json-output", str(json_output),
        "--markdown-output", str(markdown_output),
    ])

    assert code == EXIT_OK
    assert json.loads(json_output.read_text(encoding="utf-8"))["speed"]["llm_calls_delta"] == -2
    assert "质量" in markdown_output.read_text(encoding="utf-8")

    candidate.write_text(
        json.dumps(_run("candidate", calls=1, total_ms=500, unsafe=1)),
        encoding="utf-8",
    )
    assert main([
        "audit-performance",
        "--baseline", str(baseline),
        "--candidate", str(candidate),
        "--json-output", str(json_output),
        "--markdown-output", str(markdown_output),
    ]) == EXIT_FAILED

    candidate.write_text(
        json.dumps({"name": "candidate", "samples": [{"case_id": "missing"}]}),
        encoding="utf-8",
    )
    assert main([
        "audit-performance",
        "--baseline", str(baseline),
        "--candidate", str(candidate),
        "--json-output", str(json_output),
        "--markdown-output", str(markdown_output),
    ]) == EXIT_BLOCKED
