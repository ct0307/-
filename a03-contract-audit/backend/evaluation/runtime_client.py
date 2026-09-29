"""配置模型端点的只读健康探测客户端。"""
from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings
from app.core.model_policy import check_model_endpoint
from app.services.runtime.status import RuntimeProbeError


def configured_models_url() -> str:
    return f"{settings.LLM_BASE_URL.rstrip('/')}/models"


def _probe_once() -> dict[str, Any]:
    try:
        check_model_endpoint(settings.LLM_BASE_URL, settings)
    except ValueError:
        raise RuntimeProbeError("model_outbound_blocked", "模型出站策略禁止探测当前地址") from None
    headers = {"Accept": "application/json"}
    if settings.LLM_API_KEY:
        headers["Authorization"] = f"Bearer {settings.LLM_API_KEY}"
    try:
        response = httpx.get(
            configured_models_url(),
            headers=headers,
            timeout=min(float(settings.LLM_TIMEOUT), 10.0),
            **({"trust_env": False, "follow_redirects": False} if settings.MODEL_PROCESSING_MODE == "private_model" else {}),
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        code = "auth_failed" if status in {401, 403} else "endpoint_not_found" if status == 404 else "probe_failed"
        detail = "模型端点鉴权失败" if code == "auth_failed" else "模型端点不存在" if code == "endpoint_not_found" else "模型端点返回错误"
        raise RuntimeProbeError(code, detail) from None
    except httpx.TimeoutException:
        raise RuntimeProbeError("timeout", "模型端点请求超时", retryable=True) from None
    except httpx.RequestError:
        raise RuntimeProbeError("network_error", "模型端点网络连接失败", retryable=True) from None

    payload = response.json()
    model_ids = {
        str(item.get("id"))
        for item in payload.get("data", ())
        if isinstance(item, dict) and item.get("id")
    }
    if settings.LLM_MODEL in model_ids:
        return {"model": settings.LLM_MODEL}
    raise RuntimeProbeError("model_not_found", "配置的模型未在端点中找到")


def probe_configured_model() -> dict[str, Any]:
    for attempt in range(2):
        try:
            return _probe_once()
        except RuntimeProbeError as exc:
            if not exc.retryable or attempt == 1:
                raise
    raise AssertionError("unreachable")
