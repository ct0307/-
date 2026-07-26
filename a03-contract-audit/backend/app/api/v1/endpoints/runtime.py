"""模型运行时状态接口。"""
from fastapi import APIRouter

from app.core.config import settings
from app.services.runtime.status import RuntimeStatus, probe_runtime
from evaluation.runtime_client import probe_configured_model


router = APIRouter()


@router.get("/status", response_model=RuntimeStatus)
def get_runtime_status() -> RuntimeStatus:
    return probe_runtime(
        probe_configured_model,
        provider=settings.LLM_PROVIDER,
        endpoint=settings.LLM_BASE_URL,
    )
