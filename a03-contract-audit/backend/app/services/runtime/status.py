"""真实模型端点健康状态。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Literal, Mapping
from urllib.parse import urlsplit, urlunsplit


RuntimeState = Literal["online", "offline", "unknown"]


@dataclass(frozen=True)
class RuntimeStatus:
    status: RuntimeState
    checked_at: str
    provider: str | None = None
    model: str | None = None
    endpoint: str | None = None
    detail: str | None = None


def sanitize_endpoint(endpoint: str | None) -> str | None:
    if not endpoint:
        return None
    parsed = urlsplit(endpoint)
    hostname = parsed.hostname or ""
    if not hostname:
        return None
    port = f":{parsed.port}" if parsed.port is not None else ""
    return urlunsplit((parsed.scheme, f"{hostname}{port}", parsed.path.rstrip("/"), "", ""))


def probe_runtime(
    probe: Callable[[], Mapping[str, Any]],
    *,
    provider: str | None = None,
    endpoint: str | None = None,
) -> RuntimeStatus:
    checked_at = datetime.now(timezone.utc).isoformat()
    safe_endpoint = sanitize_endpoint(endpoint)
    try:
        payload = probe()
    except Exception:
        return RuntimeStatus(
            status="offline",
            checked_at=checked_at,
            provider=provider,
            endpoint=safe_endpoint,
            detail="模型端点连接失败",
        )

    model = payload.get("model") if isinstance(payload, Mapping) else None
    if not isinstance(model, str) or not model.strip():
        return RuntimeStatus(
            status="unknown",
            checked_at=checked_at,
            provider=provider,
            endpoint=safe_endpoint,
            detail="健康探测响应缺少模型标识",
        )
    return RuntimeStatus(
        status="online",
        checked_at=checked_at,
        provider=provider,
        model=model.strip(),
        endpoint=safe_endpoint,
    )
