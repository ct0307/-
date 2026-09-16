"""评测证据必须可追溯、只追加且不泄露敏感内容。"""
import hashlib
import json
from types import SimpleNamespace

import pytest

from evaluation import evidence
from evaluation.evidence import EvidenceWriter, redact, sha256_file


def test_git_state_decodes_git_output_as_utf8(monkeypatch):
    calls = []
    outputs = iter(["abc123\n", "?? 合同.docx\n"])

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout=next(outputs))

    monkeypatch.setattr(evidence.subprocess, "run", fake_run)

    assert evidence._git_state() == ("abc123", True)
    assert len(calls) == 2
    assert all(kwargs["encoding"] == "utf-8" for _, kwargs in calls)
    assert all(kwargs["errors"] == "replace" for _, kwargs in calls)
    assert all("text" not in kwargs for _, kwargs in calls)


def test_evidence_writer_creates_versioned_manifest(tmp_path):
    writer = EvidenceWriter.create(
        tmp_path,
        run_id="run-1",
        command="elements",
        git_commit="abc123",
        git_dirty=False,
    )

    manifest = json.loads((writer.run_dir / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["schema_version"] == "1.0"
    assert manifest["run_id"] == "run-1"
    assert manifest["command"] == "elements"
    assert manifest["status"] == "error"
    assert manifest["git_commit"] == "abc123"
    assert manifest["git_dirty"] is False


def test_evidence_writer_appends_events_without_overwriting(tmp_path):
    writer = EvidenceWriter.create(tmp_path, run_id="run-1", command="elements")
    writer.append("elements", {"case_id": "case-1"})
    writer.append("elements", {"case_id": "case-2"})

    rows = [
        json.loads(line)
        for line in (writer.run_dir / "elements.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert [row["payload"]["case_id"] for row in rows] == ["case-1", "case-2"]
    assert all(row["run_id"] == "run-1" for row in rows)


def test_evidence_writer_refuses_duplicate_run_id(tmp_path):
    EvidenceWriter.create(tmp_path, run_id="run-1", command="elements")

    with pytest.raises(FileExistsError):
        EvidenceWriter.create(tmp_path, run_id="run-1", command="elements")


def test_evidence_writer_rejects_unsafe_stream_name(tmp_path):
    writer = EvidenceWriter.create(tmp_path, run_id="run-1", command="elements")

    with pytest.raises(ValueError, match="事件流名称"):
        writer.append("../outside", {"status": "done"})


def test_redact_removes_nested_secrets_and_contract_content():
    payload = redact(
        {
            "Authorization": "Bearer secret",
            "access_token": "jwt-secret",
            "nested": {
                "api_key": "secret-key",
                "items": [{"contract_text": "合同正文"}, {"status": "done"}],
            },
        }
    )

    assert payload == {
        "Authorization": "[REDACTED]",
        "access_token": "[REDACTED]",
        "nested": {
            "api_key": "[REDACTED]",
            "items": [{"contract_text": "[REDACTED]"}, {"status": "done"}],
        },
    }


def test_sha256_file_binds_exact_bytes(tmp_path):
    path = tmp_path / "input.jsonl"
    path.write_bytes(b"one\n")

    assert sha256_file(path) == hashlib.sha256(b"one\n").hexdigest()


def test_manifest_update_is_atomic_and_redacted(tmp_path):
    writer = EvidenceWriter.create(tmp_path, run_id="run-1", command="elements")

    writer.write_manifest(
        status="passed",
        modules={"elements": "passed"},
        inputs={"dataset_sha256": "hash", "token": "secret"},
    )
    manifest = json.loads((writer.run_dir / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["status"] == "passed"
    assert manifest["modules"] == {"elements": "passed"}
    assert manifest["inputs"]["token"] == "[REDACTED]"
    assert not (writer.run_dir / "manifest.json.tmp").exists()
