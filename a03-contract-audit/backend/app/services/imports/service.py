"""合同导入状态、汇总和权限相关的领域规则。"""

from dataclasses import dataclass

from app.core.config import settings


class ImportConflict(ValueError):
    """导入项当前状态不允许执行请求的操作。"""


@dataclass(frozen=True)
class ImportSummary:
    total: int
    ready: int
    failed: int
    status: str


def target_status(
    suggested_type: str,
    confidence: float,
    *,
    current_status: str = "parsing",
    retry: bool = False,
) -> str:
    if retry and current_status != "failed":
        raise ImportConflict("仅失败导入项可以重试")
    if suggested_type and confidence >= settings.CONTRACT_TYPE_READY_THRESHOLD:
        return "ready"
    return "awaiting_confirmation"


def summarize_import(statuses: list[str]) -> ImportSummary:
    visible = [value for value in statuses if value != "deleted"]
    ready = visible.count("ready")
    failed = visible.count("failed")
    active = any(value in {"queued", "parsing", "auditing"} for value in visible)
    status = (
        "processing"
        if active
        else "needs_attention"
        if failed or "awaiting_confirmation" in visible
        else "ready"
    )
    return ImportSummary(len(visible), ready, failed, status)
