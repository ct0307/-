"""审查进度的领域规则与持久化发布。"""
from collections.abc import Callable
from typing import Literal

from sqlalchemy import case, or_
from sqlalchemy.orm import Session

from app.models.models import AuditBatchItem


ProgressStage = Literal[
    "queued",
    "claimed",
    "parsing",
    "reviewing",
    "discovering",
    "enriching",
    "verifying",
    "persisting",
    "completed",
    "failed",
]
ProgressCallback = Callable[[int, ProgressStage], None]
PROGRESS_STAGES = frozenset({
    "queued",
    "claimed",
    "parsing",
    "reviewing",
    "discovering",
    "enriching",
    "verifying",
    "persisting",
    "completed",
    "failed",
})
_TERMINAL_ITEM_STATUSES = ("done", "review_required", "failed")
_STATUS_PROGRESS_FALLBACK = {
    "queued": 0,
    "parsing": 5,
    "reviewing": 15,
    "validating": 90,
    "done": 100,
    "review_required": 100,
    "failed": 0,
}
_STATUS_STAGE_FALLBACK: dict[str, ProgressStage] = {
    "queued": "queued",
    "parsing": "parsing",
    "reviewing": "reviewing",
    "validating": "persisting",
    "done": "completed",
    "review_required": "completed",
    "failed": "failed",
}


def normalize_progress(value: int, *, terminal_success: bool = False) -> int:
    """限制进度范围；成功终态发布前不得提前返回 100%。"""
    upper_bound = 100 if terminal_success else 99
    return max(0, min(upper_bound, int(value)))


def progress_from_status(status: str) -> int:
    return _STATUS_PROGRESS_FALLBACK.get(status, 0)


def stage_from_status(status: str) -> ProgressStage:
    return _STATUS_STAGE_FALLBACK.get(status, "queued")


def publish_progress(
    db: Session,
    *,
    item_id: int,
    contract_id: int,
    generation: int,
    execution_token: str,
    progress: int,
    stage: ProgressStage,
) -> bool:
    """在执行围栏内发布单调进度；返回是否实际写入。"""
    if stage not in PROGRESS_STAGES:
        raise ValueError(f"未知审查进度阶段: {stage}")
    candidate = normalize_progress(progress)
    updated = (
        db.query(AuditBatchItem)
        .filter(
            AuditBatchItem.id == item_id,
            AuditBatchItem.contract_id == contract_id,
            AuditBatchItem.audit_generation == generation,
            AuditBatchItem.execution_token == execution_token,
            AuditBatchItem.status.notin_(_TERMINAL_ITEM_STATUSES),
            or_(
                AuditBatchItem.progress < candidate,
                AuditBatchItem.progress_stage != stage,
            ),
        )
        .update(
            {
                AuditBatchItem.progress: case(
                    (AuditBatchItem.progress < candidate, candidate),
                    else_=AuditBatchItem.progress,
                ),
                AuditBatchItem.progress_stage: stage,
            },
            synchronize_session=False,
        )
    )
    if updated:
        db.commit()
    else:
        db.rollback()
    return updated == 1
