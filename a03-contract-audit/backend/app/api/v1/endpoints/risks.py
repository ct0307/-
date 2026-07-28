"""风险端点：更新人工复核状态。"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.session import get_db
from app.models.models import Contract, Risk, User
from app.schemas.contract import RiskStatusUpdate
from app.services import audit_log

router = APIRouter()

_VALID_STATUS = {"pending", "confirmed", "ignored", "to_modify"}


@router.patch("/{risk_id}/status")
def update_risk_status(
    risk_id: int,
    payload: RiskStatusUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("legal", "finance")),
) -> dict:
    if payload.review_status not in _VALID_STATUS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"非法状态: {payload.review_status}")
    risk = db.query(Risk).filter(Risk.id == risk_id).first()
    if not risk:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "风险项不存在")
    old = risk.review_status
    risk.review_status = payload.review_status
    pending_count = (
        db.query(Risk)
        .filter(
            Risk.contract_id == risk.contract_id,
            Risk.id != risk.id,
            Risk.review_status.in_(("pending", "to_modify")),
        )
        .count()
    )
    if payload.review_status not in {"pending", "to_modify"} and pending_count == 0:
        contract = db.query(Contract).filter(Contract.id == risk.contract_id).first()
        if contract and contract.requires_review:
            contract.requires_review = False
            contract.review_reason = None
            contract.status = "done"
    db.commit()
    audit_log.record(
        db, user_id=user.id, action="update_risk",
        target=f"risk:{risk_id}", detail=f"{old} -> {payload.review_status}",
    )
    return {"risk_id": risk_id, "review_status": risk.review_status}
