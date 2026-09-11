"""真实模型端点健康状态。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Callable, Literal, Mapping

from app.core.url_security import safe_http_authority


RuntimeState = Literal["checking", "online", "degraded", "offline", "unknown"]


class RuntimeProbeError(RuntimeError):
    """模型探活失败的安全、机器可读错误。"""

    def __init__(self, error_code: str, detail: str, *, retryable: bool = False) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail
        self.retryable = retryable


@dataclass(frozen=True)
class RuntimeStatus:
    status: RuntimeState
    checked_at: str
    provider: str | None = None
    model: str | None = None
    endpoint: str | None = None
    detail: str | None = None
    error_code: str | None = None
    latency_ms: int | None = None


def sanitize_endpoint(endpoint: str | None) -> str | None:
    return safe_http_authority(endpoint)


def probe_runtime(
    probe: Callable[[], Mapping[str, Any]],
    *,
    provider: str | None = None,
    endpoint: str | None = None,
) -> RuntimeStatus:
    checked_at = datetime.now(timezone.utc).isoformat()
    safe_endpoint = sanitize_endpoint(endpoint)
    started_at = perf_counter()
    try:
        payload = probe()
    except RuntimeProbeError as exc:
        return RuntimeStatus(
            status="offline",
            checked_at=checked_at,
            provider=provider,
            endpoint=safe_endpoint,
            detail=exc.detail,
            error_code=exc.error_code,
            latency_ms=round((perf_counter() - started_at) * 1000),
        )
    except Exception:
        return RuntimeStatus(
            status="offline",
            checked_at=checked_at,
            provider=provider,
            endpoint=safe_endpoint,
            detail="模型端点探测失败",
            error_code="probe_failed",
            latency_ms=round((perf_counter() - started_at) * 1000),
        )

    model = payload.get("model") if isinstance(payload, Mapping) else None
    if not isinstance(model, str) or not model.strip():
        return RuntimeStatus(
            status="unknown",
            checked_at=checked_at,
            provider=provider,
            endpoint=safe_endpoint,
            detail="健康探测响应缺少模型标识",
            error_code="invalid_response",
            latency_ms=round((perf_counter() - started_at) * 1000),
        )
    return RuntimeStatus(
        status="online",
        checked_at=checked_at,
        provider=provider,
        model=model.strip(),
        endpoint=safe_endpoint,
        error_code=None,
        latency_ms=round((perf_counter() - started_at) * 1000),
    )
