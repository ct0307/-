"""报告生成器必须拒绝不完整或互相矛盾的证据。"""
import json

import pytest

from evaluation.evidence import EvidenceWriter
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
