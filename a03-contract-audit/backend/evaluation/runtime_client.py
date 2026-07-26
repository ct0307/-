"""配置模型端点的只读健康探测客户端。"""
from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings


def configured_models_url() -> str:
    return f"{settings.LLM_BASE_URL.rstrip('/')}/models"


def probe_configured_model() -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if settings.LLM_API_KEY:
        headers["Authorization"] = f"Bearer {settings.LLM_API_KEY}"
    response = httpx.get(
        configured_models_url(),
        headers=headers,
        timeout=min(float(settings.LLM_TIMEOUT), 10.0),
    )
    response.raise_for_status()
    payload = response.json()
    model_ids = {
        str(item.get("id"))
        for item in payload.get("data", ())
        if isinstance(item, dict) and item.get("id")
    }
    if settings.LLM_MODEL in model_ids:
        return {"model": settings.LLM_MODEL}
    return {}
