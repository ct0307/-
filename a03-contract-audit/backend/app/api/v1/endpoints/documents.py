"""人工复核使用的解析正文，只读取有效缓存，不触发重新解析或模型调用。"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import require_department_access, require_roles
from app.db.session import get_db
from app.models.models import Contract, User
from app.services.parser.cache import get_cached_parse

router = APIRouter()


class ContractDocumentOut(BaseModel):
    contract_id: int
    filename: str
    status: Literal["available", "unavailable", "empty"]
    text: str = ""
    source: str | None = None
    message: str = ""
    requires_review: bool = False
    review_reason: str | None = None
    total_pages: int | None = None
    missing_pages: list[int] = Field(default_factory=list)


@router.get("/{contract_id}/document", response_model=ContractDocumentOut)
def get_contract_document(
    contract_id: int,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("legal", "finance", "admin")),
) -> ContractDocumentOut:
    contract = db.get(Contract, contract_id)
    if contract is None or contract.deleted_at is not None:
        raise HTTPException(404, "合同不存在")
    require_department_access(user, contract.department)
    response.headers["Cache-Control"] = "no-store"
    parsed = get_cached_parse(db, contract)
    if parsed is None:
        return ContractDocumentOut(
            contract_id=contract.id, filename=contract.filename, status="unavailable",
            message="暂无有效解析正文，请完成合同解析后再查看。",
        )
    available = bool(parsed.text.strip())
    return ContractDocumentOut(
        contract_id=contract.id, filename=contract.filename,
        status="available" if available else "empty", text=parsed.text if available else "",
        source=parsed.source,
        message="" if available else "未提取到可阅读正文，请核对原文件及解析结果。",
        requires_review=parsed.requires_review, review_reason=parsed.review_reason,
        total_pages=parsed.total_pages, missing_pages=list(parsed.missing_pages),
    )
