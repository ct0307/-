"""模型运行时状态接口。"""
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from threading import Lock
from time import monotonic

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.core.config import settings
from app.models.models import User
from app.services.runtime.status import RuntimeState, probe_runtime
from evaluation.runtime_client import probe_configured_model


router = APIRouter()
_CACHE_TTL_SECONDS = 30.0
_runtime_status_cache: dict[str, object] = {"expires_at": 0.0, "value": None}
_runtime_status_lock = Lock()
_runtime_status_refreshing = False


@dataclass(frozen=True)
class PublicRuntimeStatus:
    status: RuntimeState
    checked_at: str
    provider: str | None = None
    model: str | None = None
    endpoint: str | None = None
    detail: str | None = None
    error_code: str | None = None
    latency_ms: int | None = None
    last_success_at: str | None = None
    processing_mode: str = "external_model"


def _get_runtime_status_snapshot() -> PublicRuntimeStatus:
    with _runtime_status_lock:
        cached = _runtime_status_cache.get("value")
        if isinstance(cached, PublicRuntimeStatus):
            if monotonic() < float(_runtime_status_cache.get("expires_at", 0.0)):
                return cached
            return replace(
                cached,
                status="degraded",
                detail="模型状态缓存已过期",
                error_code="status_stale",
            )
    return PublicRuntimeStatus(
        status="checking",
        checked_at=datetime.now(timezone.utc).isoformat(),
        detail="模型状态尚未探测",
        error_code="probe_pending",
    )


def _get_cached_runtime_status(
    *,
    now: float | None = None,
    force_refresh: bool = False,
) -> PublicRuntimeStatus:
    current = monotonic() if now is None else now
    global _runtime_status_refreshing
    with _runtime_status_lock:
        cached = _runtime_status_cache.get("value")
        if (
            not force_refresh
            and isinstance(cached, PublicRuntimeStatus)
            and current < float(_runtime_status_cache.get("expires_at", 0.0))
        ):
            return cached
        if _runtime_status_refreshing:
            if isinstance(cached, PublicRuntimeStatus):
                return replace(cached, status="degraded", detail="正在刷新模型状态")
            return PublicRuntimeStatus(status="checking", checked_at=datetime.now(timezone.utc).isoformat())
        _runtime_status_refreshing = True

    try:
        internal = probe_runtime(
            probe_configured_model,
            provider=settings.LLM_PROVIDER,
            endpoint=settings.LLM_BASE_URL,
        )
        with _runtime_status_lock:
            last_success_at = _runtime_status_cache.get("last_success_at")
            if internal.status == "online":
                last_success_at = internal.checked_at
                _runtime_status_cache["last_success_at"] = last_success_at
            public = PublicRuntimeStatus(
                status=internal.status,
                checked_at=internal.checked_at,
                provider=internal.provider,
                model=internal.model,
                endpoint=internal.endpoint,
                detail=internal.detail,
                error_code=internal.error_code,
                latency_ms=internal.latency_ms,
                last_success_at=last_success_at if isinstance(last_success_at, str) else None,
            )
            _runtime_status_cache["value"] = public
            _runtime_status_cache["expires_at"] = current + _CACHE_TTL_SECONDS
            _runtime_status_refreshing = False
            return public
    except BaseException:
        with _runtime_status_lock:
            _runtime_status_refreshing = False
        raise


@router.get("/status", response_model=PublicRuntimeStatus)
def get_runtime_status(
    _user: User = Depends(get_current_user),
) -> PublicRuntimeStatus:
    if settings.MODEL_PROCESSING_MODE == "rules_fallback":
        return PublicRuntimeStatus(status="degraded", checked_at=datetime.now(timezone.utc).isoformat(),
                                   detail="规则模式，模型调用已禁用", processing_mode="rules_fallback")
    return replace(_get_cached_runtime_status(), processing_mode=settings.MODEL_PROCESSING_MODE)
