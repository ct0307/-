"""风险人工复核接口。"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.session import get_db
from app.models.models import User
from app.schemas.contract import RiskStatusUpdate
from app.services import audit_log
from app.services.authorized_risks import load_authorized_risk

router = APIRouter()
_VALID_STATUS = {"pending", "confirmed", "ignored", "to_modify"}


@router.patch("/{risk_id}/status")
def update_risk_status(
    risk_id: int,
    payload: RiskStatusUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("legal", "finance", "admin")),
) -> dict:
    if payload.review_status not in _VALID_STATUS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"非法状态: {payload.review_status}")
    risk, _contract = load_authorized_risk(db, risk_id, user)
    comment = payload.review_comment.strip()
    if payload.review_status != "pending" and not comment:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "完成人工复核必须填写意见")
    old = risk.review_status
    risk.review_status = payload.review_status
    audit_log.record(
        db,
        user_id=user.id,
        action="update_risk",
        target=f"risk:{risk_id}",
        detail=f"{old} -> {payload.review_status};comment={comment}",
    )
    db.commit()
    return {"risk_id": risk_id, "review_status": risk.review_status}
