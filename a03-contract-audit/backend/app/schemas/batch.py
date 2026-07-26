"""异步审查批次 API 数据模型。"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

BatchStatus = Literal["queued", "running", "done", "partial_failed", "failed"]
BatchItemStatus = Literal["queued", "parsing", "auditing", "done", "failed"]


class BatchItemOut(BaseModel):
    id: int
    contract_id: int
    filename: str
    status: BatchItemStatus
    error: str | None = None
    attempts: int
    started_at: datetime | None = None
    finished_at: datetime | None = None

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
