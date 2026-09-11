"""模型运行时状态接口。"""
from dataclasses import dataclass
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


def _get_cached_runtime_status(
    *,
    now: float | None = None,
    force_refresh: bool = False,
) -> PublicRuntimeStatus:
    current = monotonic() if now is None else now
    with _runtime_status_lock:
        cached = _runtime_status_cache.get("value")
        if (
            not force_refresh
            and isinstance(cached, PublicRuntimeStatus)
            and current < float(_runtime_status_cache.get("expires_at", 0.0))
        ):
            return cached

        internal = probe_runtime(
            probe_configured_model,
            provider=settings.LLM_PROVIDER,
            endpoint=settings.LLM_BASE_URL,
        )
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
        return public


@router.get("/status", response_model=PublicRuntimeStatus)
def get_runtime_status(
    _user: User = Depends(get_current_user),
) -> PublicRuntimeStatus:
    return _get_cached_runtime_status()
