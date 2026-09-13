"""智能合同收件箱请求与响应模型。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


ImportItemStatus = Literal[
    "queued",
    "parsing",
    "awaiting_confirmation",
    "ready",
    "failed",
    "auditing",
    "done",
    "deleted",
]


class ImportItemOut(BaseModel):
    id: int
    contract_id: int | None
    filename: str
    status: ImportItemStatus
    error_code: str | None = None
    error_message: str | None = None
    suggested_type: str = ""
    confidence: float | None = None
    confirmed_type: str = ""
    department: str = ""
    requires_review: bool = False


class ImportBatchOut(BaseModel):
    id: int
    status: Literal["processing", "needs_attention", "ready"]
    total: int
    ready: int
    failed: int
    created_at: datetime
    updated_at: datetime
    items: list[ImportItemOut] = Field(default_factory=list)


class ConfirmImportItem(BaseModel):
    contract_type: str = Field(min_length=1, max_length=64)
    department: str = Field(min_length=1, max_length=64)


class ContractTrashItemOut(BaseModel):
    batch_id: int
    item_id: int
    contract_id: int
    filename: str
    contract_type: str
    department: str
    deleted_at: datetime
    expires_at: datetime
    recoverable: bool
