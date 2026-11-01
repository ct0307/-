"""异步审查批次 API 数据模型。"""
from datetime import datetime, timezone
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
from app.services.batch.timing import item_timings

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
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    queue_wait_ms: int | None = Field(default=None, ge=0, description="创建到首次领取的排队时间；未领取时为当前排队时长")
    processing_ms: int | None = Field(default=None, ge=0, description="首次领取到结束的墙钟跨度，含重试等待，不等于模型耗时")
    total_ms: int | None = Field(default=None, ge=0, description="创建到结束的总墙钟耗时，未结束时为当前跨度，未知为null")
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
            "created_at": getattr(value, "created_at", None),
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

    @model_validator(mode="after")
    def calculate_timing(self):
        timings = item_timings(
            created_at=self.created_at, started_at=self.started_at,
            finished_at=self.finished_at, status=self.status,
            now=datetime.now(timezone.utc),
        )
        self.queue_wait_ms = timings["queue_wait_ms"]
        self.processing_ms = timings["processing_ms"]
        self.total_ms = timings["total_ms"]
        return self

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
