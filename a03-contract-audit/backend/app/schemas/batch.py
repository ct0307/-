"""异步审查批次 API 数据模型。"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.services.audit.result_snapshot import quality_snapshot

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
    error: str | None = None
    error_code: str | None = None
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
            return value
        quality = quality_snapshot(value, getattr(value, "contract", None))
        return {
            field: getattr(value, field)
            for field in (
                "id", "contract_id", "filename", "status", "error", "error_code",
                "attempts", "started_at", "finished_at",
            )
        } | {
            "requires_review": quality.requires_review,
            "ocr_confidence": quality.ocr_confidence,
            "review_reason": quality.review_reason,
        }

    model_config = {"from_attributes": True}


class BatchOut(BaseModel):
    id: int
    status: BatchStatus
    total: int
    completed: int
    failed: int
    created_at: datetime
    updated_at: datetime
    items: list[BatchItemOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class BatchRetryOut(BaseModel):
    batch_id: int
    retried: int
    status: BatchStatus


class BatchFromImportRequest(BaseModel):
    import_item_ids: list[int] = Field(min_length=1, max_length=200)
    dimensions: list[str] = Field(default_factory=list)
