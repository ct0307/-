"""50+2 批量验收必须可复现并隔离异常文件。"""
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path

import pytest
import httpx

from evaluation.batch import (
    BatchSample,
    BatchSubmission,
    BatchTimeout,
    HttpBatchGateway,
    load_batch_manifest,
    run_batch_acceptance,
)
from evaluation.evidence import EvidenceWriter


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_manifest(tmp_path: Path, valid_count: int = 50, invalid_count: int = 2) -> Path:
    samples: list[dict] = []
    for index in range(valid_count):
        path = tmp_path / f"valid-{index}.txt"
        path.write_text("合同", encoding="utf-8")
        samples.append(
            {
                "path": path.name,
                "role": "valid",
                "sha256": _sha256(path),
                "expected_status": "done",
            }
        )
    for index in range(invalid_count):
        path = tmp_path / f"invalid-{index}.exe"
        path.write_bytes(b"invalid")
        samples.append(
            {
                "path": path.name,
                "role": "invalid",
                "sha256": _sha256(path),
                "expected_status": 400,
            }
        )
    manifest = tmp_path / "batch-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "contract_type": "采购合同",
                "dimensions": ["legal"],
                "samples": samples,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return manifest


@dataclass
class FakeBatchGateway:
    terminal_status: str = "done"
    submission_sizes: list[int] = field(default_factory=list)
    get_calls: int = 0

    def submit(self, samples, *, idempotency_key, contract_type, dimensions):
        self.submission_sizes.append(len(samples))
        if samples[0].role == "invalid":
            return BatchSubmission(
                batch_id=None,
                http_status=int(samples[0].expected_status),
                payload={"detail": "invalid"},
            )
        return BatchSubmission(batch_id=7, http_status=202, payload={"id": 7})

    def get(self, batch_id):
        self.get_calls += 1
        item_status = "done" if self.terminal_status == "done" else "auditing"
        return {
            "id": batch_id,
            "status": self.terminal_status,
            "total": 50,
            "completed": 50 if self.terminal_status == "done" else 0,
            "failed": 0,
            "items": [
                {"id": index, "status": item_status, "filename": f"private-{index}.txt"}
                for index in range(50)
            ],
        }


def test_batch_manifest_requires_exactly_fifty_valid_and_two_invalid(tmp_path):
    manifest_path = _make_manifest(tmp_path, valid_count=49, invalid_count=2)

    with pytest.raises(ValueError, match="50 个 valid"):
        load_batch_manifest(manifest_path)


def test_batch_manifest_rejects_hash_mismatch(tmp_path):
    manifest_path = _make_manifest(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["samples"][0]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="SHA-256"):
        load_batch_manifest(manifest_path)


def test_batch_runner_submits_valid_together_and_invalid_separately(tmp_path):
    gateway = FakeBatchGateway()

    result = run_batch_acceptance(
        load_batch_manifest(_make_manifest(tmp_path)),
        gateway=gateway,
        run_id="batch-run",
        poll_interval=0,
        timeout_seconds=5,
    )

    assert gateway.submission_sizes == [50, 1, 1]
    assert gateway.get_calls >= 2
    assert result.status == "passed"
    assert result.valid_count == 50
    assert result.invalid_count == 2


def test_batch_runner_fails_when_valid_batch_is_not_fully_done(tmp_path):
    gateway = FakeBatchGateway(terminal_status="partial_failed")

    result = run_batch_acceptance(
        load_batch_manifest(_make_manifest(tmp_path)),
        gateway=gateway,
        run_id="batch-run",
        poll_interval=0,
        timeout_seconds=5,
    )

    assert result.status == "failed"
    assert "partial_failed" in result.reasons[0]


def test_batch_runner_times_out_without_infinite_polling(tmp_path):
    gateway = FakeBatchGateway(terminal_status="running")

    with pytest.raises(BatchTimeout, match="批次轮询超时"):
        run_batch_acceptance(
            load_batch_manifest(_make_manifest(tmp_path)),
            gateway=gateway,
            run_id="batch-run",
            poll_interval=0,
            timeout_seconds=0,
        )


def test_batch_evidence_omits_private_filenames_and_payload_details(tmp_path):
    writer = EvidenceWriter.create(
        tmp_path / "runs",
        run_id="batch-run",
        command="batch",
        git_commit="abc123",
        git_dirty=False,
    )

    run_batch_acceptance(
        load_batch_manifest(_make_manifest(tmp_path)),
        gateway=FakeBatchGateway(),
        writer=writer,
        run_id="batch-run",
        poll_interval=0,
        timeout_seconds=5,
    )
    evidence = (writer.run_dir / "batch-events.jsonl").read_text(encoding="utf-8")

    assert "private-0.txt" not in evidence
    assert "valid-0.txt" not in evidence
    assert '"detail"' not in evidence
    assert '"status": "done"' in evidence


def test_http_batch_gateway_sends_streamed_multipart_with_auth(tmp_path):
    path = tmp_path / "contract.txt"
    path.write_text("合同", encoding="utf-8")
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("Authorization")
        captured["idempotency"] = request.headers.get("Idempotency-Key")
        captured["content_type"] = request.headers.get("Content-Type")
        captured["body"] = request.read()
        return httpx.Response(202, json={"id": 9})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    gateway = HttpBatchGateway(
        "http://test/api/v1",
        token="secret-token",
        client=client,
    )

    submission = gateway.submit(
        [BatchSample(path, "valid", _sha256(path), "done")],
        idempotency_key="request-123",
        contract_type="采购合同",
        dimensions=["legal"],
    )

    assert submission.batch_id == 9
    assert captured["authorization"] == "Bearer secret-token"
    assert captured["idempotency"] == "request-123"
    assert captured["content_type"].startswith("multipart/form-data;")
    assert b'filename="contract.txt"' in captured["body"]
