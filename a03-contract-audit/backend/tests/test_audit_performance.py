import json
import pytest

from evaluation.audit_performance import compare_runs, render_markdown
from evaluation.cli import EXIT_BLOCKED, EXIT_FAILED, EXIT_OK, main


def _run(name: str, *, calls: int, total_ms: int, unsafe: int = 0) -> dict:
    return {
        "name": name,
        "identity": {
            "dataset_sha256": "dataset-v1", "model": "frozen-test-model",
            "prompt_sha256": "prompt-v1", "knowledge_revision": 1,
            "dimensions": ["legal", "payment"], "concurrency": 2,
            "deadline_seconds": 1500,
        },
        "quality_metrics": {
            "high_risk_recall": 0.95, "risk_f1": 0.9,
            "evidence_support_rate": 0.98, "coverage_rate": 1.0,
            "manual_review_rate": 0.2,
        },
        "samples": [
            {
                "case_id": "case-1",
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


def test_quality_gate_rejects_model_and_case_identity_mismatch():
    baseline = _run("baseline", calls=2, total_ms=1000)
    candidate = _run("candidate", calls=1, total_ms=500)
    candidate["identity"]["model"] = "other-model"
    assert compare_runs(baseline, candidate).quality.gate_passed is False
    candidate["identity"] = baseline["identity"]
    candidate["samples"][0]["case_id"] = "other-case"
    assert compare_runs(baseline, candidate).quality.gate_passed is False


@pytest.mark.parametrize("field,value", [
    ("model", ""), ("dataset_sha256", " "), ("prompt_sha256", ""),
    ("dimensions", []), ("concurrency", 0), ("deadline_seconds", True),
    ("knowledge_revision", -1),
])
def test_invalid_identity_blocks_rollout(field, value):
    baseline = _run("baseline", calls=2, total_ms=1000)
    candidate = _run("candidate", calls=1, total_ms=500)
    baseline["identity"][field] = candidate["identity"][field] = value
    assert compare_runs(baseline, candidate).quality.gate_passed is None


def test_missing_business_quality_metrics_block_rollout_even_if_safety_counts_are_zero():
    baseline = _run("baseline", calls=2, total_ms=1000)
    candidate = _run("candidate", calls=1, total_ms=500)
    candidate.pop("quality_metrics")
    report = compare_runs(baseline, candidate)
    assert report.quality.gate_passed is None
    assert "candidate.quality_metrics" in report.unavailable_metrics


def test_quality_gate_rejects_recall_regression_and_manual_review_increase():
    baseline = _run("baseline", calls=2, total_ms=1000)
    candidate = _run("candidate", calls=1, total_ms=500)
    candidate["quality_metrics"]["high_risk_recall"] = 0.8
    assert compare_runs(baseline, candidate).quality.gate_passed is False
    candidate["quality_metrics"] = dict(baseline["quality_metrics"])
    candidate["quality_metrics"]["manual_review_rate"] = 0.8
    assert compare_runs(baseline, candidate).quality.gate_passed is False


def test_performance_report_separates_speed_and_quality():
    baseline = _run("baseline", calls=10, total_ms=1000)
    candidate = _run("candidate", calls=2, total_ms=600)

    report = compare_runs(baseline, candidate)

    assert report.speed.llm_calls_delta == -8
    assert report.speed.total_ms_delta == -400
    assert report.quality.unauthorized_evidence_count == 0
    assert report.quality.unverified_auto_publish_count == 0
    assert report.quality.gate_passed is True
    assert report.speed.candidate.total_latency_p50_ms == 600
    assert report.speed.candidate.total_latency_p95_ms == 600


def test_explicit_safety_violation_fails_even_when_business_metrics_are_missing():
    baseline = _run("baseline", calls=2, total_ms=1000)
    candidate = _run("candidate", calls=1, total_ms=500, unsafe=1)
    candidate.pop("quality_metrics")
    assert compare_runs(baseline, candidate).quality.gate_passed is False


def test_partial_safety_counts_do_not_hide_known_violation():
    baseline = _run("baseline", calls=2, total_ms=1000)
    candidate = _run("candidate", calls=1, total_ms=500, unsafe=1)
    candidate["samples"].append({"case_id": "missing-metrics"})
    assert compare_runs(baseline, candidate).quality.gate_passed is False


@pytest.mark.parametrize("value", [-1, 0.5, True, float("nan"), float("inf")])
def test_invalid_safety_counts_cannot_pass_gate(value):
    baseline = _run("baseline", calls=2, total_ms=1000)
    candidate = _run("candidate", calls=1, total_ms=500)
    candidate["samples"][0]["unauthorized_evidence_count"] = value
    with pytest.raises(ValueError):
        compare_runs(baseline, candidate)


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
    assert "high_risk_recall" in markdown
    assert report.to_dict()["quality"]["candidate_business_metrics"]["high_risk_recall"] == 0.95


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
