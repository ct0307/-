"""50 份有效合同加 2 份异常文件的可复现批量验收执行器。"""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
import json
from pathlib import Path
import re
import time
from typing import Any, Literal, Mapping, Protocol, Sequence

import httpx

from evaluation.evidence import EvidenceWriter, sha256_file


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TERMINAL_STATUSES = frozenset({"done", "partial_failed", "failed"})


class BatchTimeout(RuntimeError):
    """批次在验收总超时内没有进入终态。"""


class BatchUnavailable(RuntimeError):
    """批次服务端点不可达。"""


@dataclass(frozen=True)
class BatchSample:
    path: Path
    role: Literal["valid", "invalid"]
    sha256: str
    expected_status: int | str


@dataclass(frozen=True)
class BatchManifest:
    schema_version: str
    contract_type: str
    dimensions: tuple[str, ...]
    samples: tuple[BatchSample, ...]


@dataclass(frozen=True)
class BatchSubmission:
    batch_id: int | None
    http_status: int
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class BatchAcceptanceResult:
    status: Literal["passed", "failed"]
    valid_count: int
    invalid_count: int
    valid_batch_id: int | None
    reasons: tuple[str, ...]


class BatchGateway(Protocol):
    def submit(
        self,
        samples: Sequence[BatchSample],
        *,
        idempotency_key: str,
        contract_type: str,
        dimensions: Sequence[str],
    ) -> BatchSubmission:
        raise NotImplementedError

    def get(self, batch_id: int) -> Mapping[str, Any]:
        raise NotImplementedError


class HttpBatchGateway:
    def __init__(
        self,
        base_url: str,
        *,
        token: str,
        timeout_seconds: float = 120,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def submit(
        self,
        samples: Sequence[BatchSample],
        *,
        idempotency_key: str,
        contract_type: str,
        dimensions: Sequence[str],
    ) -> BatchSubmission:
        headers = {**self._headers, "Idempotency-Key": idempotency_key}
        form_data = [("contract_type", contract_type)] + [
            ("dimensions", dimension) for dimension in dimensions
        ]
        try:
            with ExitStack() as stack:
                files = [
                    (
                        "files",
                        (
                            sample.path.name,
                            stack.enter_context(sample.path.open("rb")),
                            "application/octet-stream",
                        ),
                    )
                    for sample in samples
                ]
                response = self._client.post(
                    f"{self._base_url}/batches",
                    headers=headers,
                    data=form_data,
                    files=files,
                )
        except httpx.RequestError as exc:
            raise BatchUnavailable(f"批次提交端点不可达: {type(exc).__name__}") from exc
        payload = self._response_payload(response)
        batch_id = payload.get("id") if response.status_code == 202 else None
        return BatchSubmission(
            batch_id=int(batch_id) if isinstance(batch_id, int) else None,
            http_status=response.status_code,
            payload=payload,
        )

    def get(self, batch_id: int) -> Mapping[str, Any]:
        try:
            response = self._client.get(
                f"{self._base_url}/batches/{batch_id}",
                headers=self._headers,
            )
            response.raise_for_status()
        except httpx.RequestError as exc:
            raise BatchUnavailable(f"批次查询端点不可达: {type(exc).__name__}") from exc
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"批次查询返回 HTTP {exc.response.status_code}") from exc
        return self._response_payload(response)

    @staticmethod
    def _response_payload(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            return {}
        return payload if isinstance(payload, dict) else {}


def load_batch_manifest(path: Path) -> BatchManifest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"批测清单不是有效 JSON: {path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        raise ValueError("批测清单 schema_version 必须为 1.0")
    contract_type = str(payload.get("contract_type", "")).strip()
    if not contract_type:
        raise ValueError("批测清单 contract_type 不能为空")
    dimensions = payload.get("dimensions", [])
    if not isinstance(dimensions, list) or any(
        not isinstance(item, str) or not item.strip() for item in dimensions
    ):
        raise ValueError("批测清单 dimensions 必须是非空字符串数组")
    rows = payload.get("samples")
    if not isinstance(rows, list):
        raise ValueError("批测清单 samples 必须是数组")

    samples: list[BatchSample] = []
    seen_paths: set[Path] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"samples[{index}] 必须是对象")
        role = row.get("role")
        if role not in {"valid", "invalid"}:
            raise ValueError(f"samples[{index}].role 必须是 valid 或 invalid")
        sample_path = Path(str(row.get("path", "")))
        if not sample_path.is_absolute():
            sample_path = path.parent / sample_path
        sample_path = sample_path.resolve()
        if not sample_path.is_file():
            raise ValueError(f"样本文件不存在: {sample_path}")
        if sample_path in seen_paths:
            raise ValueError(f"样本文件重复: {sample_path}")
        seen_paths.add(sample_path)
        expected_hash = str(row.get("sha256", "")).lower()
        if not _SHA256.fullmatch(expected_hash) or sha256_file(sample_path) != expected_hash:
            raise ValueError(f"样本 SHA-256 不匹配: samples[{index}]")
        expected_status = row.get("expected_status")
        if role == "valid" and expected_status != "done":
            raise ValueError(f"valid 样本必须期望 done: samples[{index}]")
        if role == "invalid" and (
            not isinstance(expected_status, int) or not 400 <= expected_status < 500
        ):
            raise ValueError(f"invalid 样本必须声明 4xx 状态码: samples[{index}]")
        samples.append(
            BatchSample(
                path=sample_path,
                role=role,
                sha256=expected_hash,
                expected_status=expected_status,
            )
        )

    valid_count = sum(sample.role == "valid" for sample in samples)
    invalid_count = sum(sample.role == "invalid" for sample in samples)
    if valid_count != 50:
        raise ValueError(f"批测清单必须包含 50 个 valid 样本，实际为 {valid_count}")
    if invalid_count != 2:
        raise ValueError(f"批测清单必须包含 2 个 invalid 样本，实际为 {invalid_count}")
    return BatchManifest(
        schema_version="1.0",
        contract_type=contract_type,
        dimensions=tuple(item.strip() for item in dimensions),
        samples=tuple(samples),
    )


def _safe_batch_state(payload: Mapping[str, Any]) -> dict[str, Any]:
    items = payload.get("items", [])
    safe_items = [
        {
            "id": item.get("id"),
            "status": item.get("status"),
            "attempts": item.get("attempts"),
            "requires_review": item.get("requires_review"),
        }
        for item in items
        if isinstance(item, Mapping)
    ]
    return {
        "event": "batch_state",
        "batch_id": payload.get("id"),
        "status": payload.get("status"),
        "total": payload.get("total"),
        "completed": payload.get("completed"),
        "failed": payload.get("failed"),
        "items": safe_items,
    }


def _poll_until_terminal(
    gateway: BatchGateway,
    batch_id: int,
    *,
    writer: EvidenceWriter | None,
    poll_interval: float,
    timeout_seconds: float,
) -> Mapping[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        payload = gateway.get(batch_id)
        if writer is not None:
            writer.append("batch-events", _safe_batch_state(payload))
        if payload.get("status") in _TERMINAL_STATUSES:
            return payload
        if time.monotonic() >= deadline:
            raise BatchTimeout(f"批次轮询超时: batch_id={batch_id}, timeout={timeout_seconds}s")
        time.sleep(poll_interval)


def _valid_batch_reasons(payload: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    items = payload.get("items")
    if payload.get("status") != "done":
        reasons.append(f"有效批次终态不是 done: {payload.get('status')}")
    if payload.get("total") != 50 or payload.get("completed") != 50:
        reasons.append("有效批次没有完成全部 50 个样本")
    if payload.get("failed") != 0:
        reasons.append(f"有效批次存在失败项: {payload.get('failed')}")
    if not isinstance(items, list) or len(items) != 50 or any(
        not isinstance(item, Mapping) or item.get("status") != "done" for item in items
    ):
        reasons.append("有效批次 item 终态不完整")
    return reasons


def run_batch_acceptance(
    manifest: BatchManifest,
    *,
    gateway: BatchGateway,
    run_id: str,
    writer: EvidenceWriter | None = None,
    poll_interval: float = 1.0,
    timeout_seconds: float = 900,
) -> BatchAcceptanceResult:
    if poll_interval < 0 or timeout_seconds < 0:
        raise ValueError("轮询间隔和总超时不能为负数")
    valid = [sample for sample in manifest.samples if sample.role == "valid"]
    invalid = [sample for sample in manifest.samples if sample.role == "invalid"]
    submission = gateway.submit(
        valid,
        idempotency_key=f"{run_id}-valid",
        contract_type=manifest.contract_type,
        dimensions=manifest.dimensions,
    )
    if writer is not None:
        writer.append(
            "batch-events",
            {
                "event": "valid_submitted",
                "http_status": submission.http_status,
                "batch_id": submission.batch_id,
                "sample_count": len(valid),
            },
        )

    reasons: list[str] = []
    terminal: Mapping[str, Any] = {}
    if submission.http_status != 202 or submission.batch_id is None:
        reasons.append(f"有效批次提交失败: HTTP {submission.http_status}")
    else:
        terminal = _poll_until_terminal(
            gateway,
            submission.batch_id,
            writer=writer,
            poll_interval=poll_interval,
            timeout_seconds=timeout_seconds,
        )
        reasons.extend(_valid_batch_reasons(terminal))
        refreshed = gateway.get(submission.batch_id)
        if writer is not None:
            writer.append("batch-events", _safe_batch_state(refreshed))
        if (
            refreshed.get("status") != terminal.get("status")
            or refreshed.get("completed") != terminal.get("completed")
            or refreshed.get("failed") != terminal.get("failed")
        ):
            reasons.append("刷新后批次终态不一致")

    for index, sample in enumerate(invalid, 1):
        invalid_submission = gateway.submit(
            [sample],
            idempotency_key=f"{run_id}-invalid-{index}",
            contract_type=manifest.contract_type,
            dimensions=manifest.dimensions,
        )
        if writer is not None:
            writer.append(
                "batch-events",
                {
                    "event": "invalid_submitted",
                    "sample_index": index,
                    "sample_sha256": sample.sha256,
                    "http_status": invalid_submission.http_status,
                },
            )
        if invalid_submission.http_status != sample.expected_status:
            reasons.append(
                f"异常样本 {index} 期望 HTTP {sample.expected_status}，实际 {invalid_submission.http_status}"
            )

    status: Literal["passed", "failed"] = "failed" if reasons else "passed"
    return BatchAcceptanceResult(
        status=status,
        valid_count=len(valid),
        invalid_count=len(invalid),
        valid_batch_id=submission.batch_id,
        reasons=tuple(reasons),
    )
