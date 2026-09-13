"""报告生成器必须拒绝不完整或互相矛盾的证据。"""
import json

import pytest

from evaluation.evidence import EvidenceWriter
from evaluation.cli import EXIT_INVALID, main
from evaluation.report import InvalidEvidence, aggregate_status, build_report


def _elements_run(tmp_path, *, status: str = "passed"):
    writer = EvidenceWriter.create(
        tmp_path,
        run_id="run-1",
        command="elements",
        git_commit="abc123",
        git_dirty=False,
        inputs={
            "gold_sha256": "a" * 64,
            "predictions_sha256": "b" * 64,
            "schema_sha256": "c" * 64,
            "sample_count": 1,
            "min_f1": 0.9,
        },
    )
    writer.append(
        "elements",
        {
            "event": "case",
            "case_id": "case-1",
            "contract_type": "采购合同",
            "document_kind": "pdf",
            "field_metrics": {},
        },
    )
    writer.append(
        "elements",
        {
            "event": "summary",
            "sample_count": 1,
            "overall": {"precision": 1.0, "recall": 1.0, "f1": 1.0},
            "by_field": {},
            "by_contract_type": {},
            "by_document_kind": {},
            "error_count": 0,
            "errors": [],
        },
    )
    writer.write_manifest(status=status, modules={"elements": status})
    return writer.run_dir


def test_report_refuses_missing_stream_declared_by_manifest(tmp_path):
    run_dir = _elements_run(tmp_path)
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["modules"] = {
        "elements": "passed",
        "batch": "passed",
        "benchmark": "passed",
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(InvalidEvidence, match="batch-events.jsonl"):
        build_report(run_dir)


@pytest.mark.parametrize(
    ("limit_name", "limit"),
    [
        ("MAX_MANIFEST_BYTES", 8),
        ("MAX_EVENT_BYTES", 8),
        ("MAX_EVENT_LINES", 1),
        ("MAX_EVENT_LINE_BYTES", 8),
    ],
)
def test_report_cli_returns_invalid_when_evidence_exceeds_configured_limit(
    monkeypatch, tmp_path, limit_name, limit
):
    run_dir = _elements_run(tmp_path)
    monkeypatch.setattr(f"evaluation.report.{limit_name}", limit)

    code = main(["report", "--run-dir", str(run_dir)])

    assert code == EXIT_INVALID
    assert not (run_dir / "report.md").exists()


@pytest.mark.parametrize(
    ("statuses", "overall"),
    [
        ({"elements": "passed", "batch": "passed", "benchmark": "passed"}, "passed"),
        ({"elements": "passed", "batch": "blocked", "benchmark": "passed"}, "blocked"),
        ({"elements": "failed", "batch": "blocked", "benchmark": "passed"}, "failed"),
        ({"elements": "error", "batch": "passed", "benchmark": "passed"}, "error"),
    ],
)
def test_report_status_precedence(statuses, overall):
    assert aggregate_status(statuses) == overall


def test_report_refuses_event_from_another_run(tmp_path):
    run_dir = _elements_run(tmp_path)
    events_path = run_dir / "elements.jsonl"
    rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    rows[0]["run_id"] = "tampered-run"
    events_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )

    with pytest.raises(InvalidEvidence, match="run_id"):
        build_report(run_dir)


def test_report_builds_markdown_for_complete_elements_run(tmp_path):
    run_dir = _elements_run(tmp_path)

    result = build_report(run_dir)
    report = (run_dir / "report.md").read_text(encoding="utf-8")

    assert result.status == "passed"
    assert result.path == run_dir / "report.md"
    assert "elements" in report
    assert "1.0000" in report
    assert "甲公司" not in report


def test_report_builds_blocked_report_without_claiming_passed(tmp_path):
    writer = EvidenceWriter.create(
        tmp_path,
        run_id="blocked-run",
        command="batch",
        git_commit="abc123",
        git_dirty=False,
        inputs={"manifest_sha256": "a" * 64, "valid_count": 50, "invalid_count": 2},
    )
    writer.append("batch-events", {"event": "blocked", "reason": "端点不可达"})
    writer.write_manifest(status="blocked", modules={"batch": "blocked"})

    result = build_report(writer.run_dir)
    report = result.path.read_text(encoding="utf-8")

    assert result.status == "blocked"
    assert "blocked" in report
    assert "passed" not in report


def _audit_run(tmp_path, *, basis: str = "synthetic"):
    writer = EvidenceWriter.create(
        tmp_path,
        run_id="audit-run",
        command="audit-quality",
        git_commit="abc123",
        git_dirty=False,
        inputs={
            "gold_sha256": "a" * 64,
            "predictions_sha256": "b" * 64,
            "sample_count": 1,
            "evaluation_basis": basis,
        },
    )
    writer.append(
        "audit",
        {
            "event": "case",
            "case_id": "case-1",
            "status": "done",
            "gold_risk_count": 1,
            "high_gold_risk_count": 1,
            "predicted_risk_count": 1,
            "matched_risk_count": 1,
            "matched_high_risk_count": 1,
            "quote_located_count": 1,
            "invalid_legal_citation_count": 0,
            "truncated": False,
            "coverage": {"completed": 1, "total": 1},
            "call_count": 1,
            "valid_json_call_count": 1,
            "prompt_tokens": 80,
            "completion_tokens": 20,
            "latency_ms": 50.0,
            "cost": 0.01,
            "cost_evidence_complete": True,
            "cost_metadata": {
                "currency": "CNY",
                "pricing_source": "provider-price-page",
                "pricing_version": "2026-09-01",
            },
            "successful": True,
        },
    )
    writer.append(
        "audit",
        {
            "event": "summary",
            "sample_count": 1,
            "evaluation_basis": basis,
            "input_hashes": {
                "gold_sha256": "a" * 64,
                "predictions_sha256": "b" * 64,
            },
            "overall": {
                "high_risk_recall": 1.0,
                "false_success_rate": 0.0,
                "final_truncation_rate": 0.0,
                "quote_location_rate": 1.0,
                "invalid_legal_citation_rate": 0.0,
                "risk_recall": 1.0,
                "risk_precision": 1.0,
                "json_valid_rate": 1.0,
                "manual_review_rate": 0.0,
                "mean_prompt_tokens": 80.0,
                "mean_completion_tokens": 20.0,
                "mean_cost_per_success": 0.01,
                "p95_latency_ms": 50.0,
            },
            "quality_gate_failures": [],
            "cost_evidence_complete": True,
            "cost_metadata": {
                "currency": "CNY",
                "pricing_source": "provider-price-page",
                "pricing_version": "2026-09-01",
            },
        },
    )
    writer.write_manifest(status="passed", modules={"audit": "passed"})
    return writer.run_dir


def test_report_distinguishes_synthetic_technical_pre_evaluation(tmp_path):
    run_dir = _audit_run(tmp_path, basis="synthetic")

    result = build_report(run_dir)
    report = result.path.read_text(encoding="utf-8")

    assert "合成数据技术预评测" in report
    assert "人工金标准评测" not in report
    assert "准确率达标" not in report


@pytest.mark.parametrize("tampered", ["sample_count", "input_hash", "gate_status"])
def test_report_rejects_inconsistent_audit_summary(tmp_path, tampered):
    run_dir = _audit_run(tmp_path)
    events_path = run_dir / "audit.jsonl"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    summary = events[-1]["payload"]
    if tampered == "sample_count":
        summary["sample_count"] = 2
    elif tampered == "input_hash":
        summary["input_hashes"]["gold_sha256"] = "f" * 64
    else:
        summary["quality_gate_failures"] = ["risk_recall"]
    events_path.write_text(
        "".join(json.dumps(row) + "\n" for row in events), encoding="utf-8"
    )

    with pytest.raises(InvalidEvidence):
        build_report(run_dir)


def test_report_recomputes_quality_from_case_events_instead_of_trusting_summary(tmp_path):
    run_dir = _audit_run(tmp_path)
    events_path = run_dir / "audit.jsonl"
    events = [
        json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()
    ]
    case = events[0]["payload"]
    case.update(
        status="review_required",
        predicted_risk_count=0,
        matched_risk_count=0,
        matched_high_risk_count=0,
        quote_located_count=0,
        call_count=0,
        valid_json_call_count=0,
        prompt_tokens=0,
        completion_tokens=0,
        latency_ms=0.0,
        cost=0.0,
        cost_evidence_complete=False,
        cost_metadata=None,
        successful=False,
    )
    events_path.write_text(
        "".join(json.dumps(row) + "\n" for row in events), encoding="utf-8"
    )

    with pytest.raises(InvalidEvidence):
        build_report(run_dir)


def test_report_rejects_failed_case_with_synchronized_nonzero_match_counts(tmp_path):
    run_dir = _audit_run(tmp_path)
    events_path = run_dir / "audit.jsonl"
    events = [
        json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()
    ]
    case = events[0]["payload"]
    case.update(status="audit_failed", successful=False)
    summary = events[-1]["payload"]
    summary["overall"]["false_success_rate"] = None
    summary["overall"]["mean_cost_per_success"] = None
    summary["quality_gate_failures"] = ["false_success_rate"]
    events_path.write_text(
        "".join(json.dumps(row) + "\n" for row in events), encoding="utf-8"
    )
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["status"] = "failed"
    manifest["modules"] = {"audit": "failed"}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(InvalidEvidence):
        build_report(run_dir)


def test_report_rejects_comparison_selected_value_that_contradicts_ranking(tmp_path):
    writer = EvidenceWriter.create(
        tmp_path,
        run_id="comparison-run",
        command="audit-compare",
        git_commit="abc123",
        git_dirty=False,
        inputs={
            "candidate_count": 3,
            "candidate_names": ["A", "B", "C"],
            "candidate_inputs": [
                {
                    "position": index,
                    "candidate": group,
                    "input_sha256": group.lower() * 64,
                    "sample_count": 1,
                }
                for index, group in enumerate("ABC")
            ],
            "evaluation_basis": "human_gold",
        },
    )
    frozen = {
        "model_version": "model-v1",
        "prompt_version": "prompt-v1",
        "knowledge_base_version": "kb-v1",
        "dataset_version": "dataset-v1",
        "temperature": 0.2,
        "environment": "test-env",
    }
    scopes = {"A": "baseline", "B": "output_budget_only", "C": "selective_cascade"}
    for index, group in enumerate("ABC", 1):
        writer.append(
            "audit-comparison",
            {
                "event": "candidate",
                "candidate": group,
                "position": index - 1,
                "input_sha256": group.lower() * 64,
                "sample_count": 1,
                "evaluation_basis": "human_gold",
                "input_hashes": {
                    "gold_sha256": "d" * 64,
                    "predictions_sha256": group.lower() * 64,
                },
                "overall": {
                    "high_risk_recall": 1.0,
                    "false_success_rate": 0.0,
                    "final_truncation_rate": 0.0,
                    "quote_location_rate": 1.0,
                    "invalid_legal_citation_rate": 0.0,
                    "risk_recall": 1.0,
                    "risk_precision": 1.0,
                    "json_valid_rate": 1.0,
                    "mean_cost_per_success": index / 100,
                    "mean_prompt_tokens": 100.0,
                    "mean_completion_tokens": 20.0,
                    "p95_latency_ms": 10.0,
                },
                "cost_evidence_complete": True,
                "cost_metadata": {
                    "currency": "CNY",
                    "pricing_source": "source",
                    "pricing_version": "v1",
                },
                "experiment": {
                    "group": group,
                    "git_commit": "94c8f9f" if group == "A" else group.lower(),
                    "change_scope": scopes[group],
                    "output_budget": {"A": 1600, "B": 2400, "C": 1600}[group],
                    "frozen_context": frozen,
                },
            },
        )
    writer.append(
        "audit-comparison",
        {
            "event": "summary",
            "status": "passed",
            "selected": "B",
            "evaluation_basis": "human_gold",
            "contract_errors": [],
            "quality_passed": ["A", "B", "C"],
            "rejected": {},
            "ranking": ["A", "B", "C"],
            "cost_inconclusive": [],
            "thresholds": {
                "high_risk_recall": {"operator": "min", "value": 0.95},
                "false_success_rate": {"operator": "max", "value": 0.0},
                "final_truncation_rate": {"operator": "max", "value": 0.0},
                "quote_location_rate": {"operator": "min", "value": 1.0},
                "invalid_legal_citation_rate": {"operator": "max", "value": 0.0},
                "risk_recall": {"operator": "min", "value": 0.9},
                "risk_precision": {"operator": "min", "value": 0.85},
                "json_valid_rate": {"operator": "min", "value": 1.0},
            },
        },
    )
    writer.write_manifest(status="passed", modules={"audit_comparison": "passed"})

    with pytest.raises(InvalidEvidence, match="selected"):
        build_report(writer.run_dir)


def test_report_wraps_unhashable_candidate_names_as_invalid_evidence(tmp_path):
    writer = EvidenceWriter.create(
        tmp_path,
        run_id="malformed-comparison",
        command="audit-compare",
        git_commit="abc123",
        git_dirty=False,
        inputs={
            "candidate_count": 1,
            "candidate_names": [{"not": "a-name"}],
            "candidate_input_sha256": {"a": "a" * 64},
            "sample_count_by_candidate": {"a": 1},
        },
    )
    writer.append("audit-comparison", {"event": "summary"})
    writer.write_manifest(status="failed", modules={"audit_comparison": "failed"})

    with pytest.raises(InvalidEvidence, match="候选集"):
        build_report(writer.run_dir)
