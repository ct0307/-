"""异步审查批次 API 数据模型。"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.services.audit.result_snapshot import quality_snapshot
from app.services.audit.failure import audit_failure
from app.services.audit.progress import (
    ProgressStage,
    progress_from_status,
    stage_from_status,
)
from app.services.batch.service import summarize

BatchStatus = Literal[
    "queued", "running", "done", "review_required", "partial_failed", "failed",
]
BatchItemStatus = Literal[
    "queued", "parsing", "reviewing", "validating", "done", "review_required", "failed",
]


class BatchItemOut(BaseModel):
    id: int
    contract_id: int
    filename: str
    status: BatchItemStatus
    progress: int = Field(default=0, ge=0, le=100)
    progress_stage: ProgressStage = "queued"
    error: str | None = None
    error_code: str | None = None
    retryable: bool = False
    error_action: str | None = None
    attempts: int
    started_at: datetime | None = None
    finished_at: datetime | None = None
    requires_review: bool = False
    ocr_confidence: float | None = None
    review_reason: str | None = None

    @model_validator(mode="before")
    @classmethod
    def read_historical_quality_snapshot(cls, value):
        if isinstance(value, dict):
            data = dict(value)
            status = str(data.get("status", "queued"))
            data.setdefault("progress", progress_from_status(status))
            data.setdefault("progress_stage", stage_from_status(status))
            failure = audit_failure(value)
            if failure is not None:
                data.update(error=failure.message, error_code=failure.code,
                            retryable=failure.retryable, error_action=failure.action)
            return data
        quality = quality_snapshot(value, getattr(value, "contract", None))
        status = getattr(value, "status")
        data = {
            field: getattr(value, field)
            for field in (
                "id", "contract_id", "filename", "status", "error", "error_code",
                "attempts", "started_at", "finished_at",
            )
        } | {
            "progress": getattr(value, "progress", progress_from_status(status)),
            "progress_stage": getattr(
                value, "progress_stage", stage_from_status(status),
            ),
            "requires_review": quality.requires_review,
            "ocr_confidence": quality.ocr_confidence,
            "review_reason": quality.review_reason,
        }
        failure = audit_failure(value)
        if failure is not None:
            data.update(error=failure.message, error_code=failure.code,
                        retryable=failure.retryable, error_action=failure.action)
        return data

    model_config = {"from_attributes": True}


class BatchOut(BaseModel):
    id: int
    status: BatchStatus
    total: int
    completed: int
    failed: int
    progress: int = Field(default=0, ge=0, le=100)
    created_at: datetime
    updated_at: datetime
    items: list[BatchItemOut] = Field(default_factory=list)

    @model_validator(mode="after")
    def calculate_progress(self):
        self.progress = summarize(
            [item.status for item in self.items],
            progresses=[item.progress for item in self.items],
        ).progress
        return self

    model_config = {"from_attributes": True}


class BatchRetryOut(BaseModel):
    batch_id: int
    retried: int
    status: BatchStatus


class BatchFromImportRequest(BaseModel):
    import_item_ids: list[int] = Field(min_length=1, max_length=200)
    dimensions: list[str] = Field(default_factory=list)
