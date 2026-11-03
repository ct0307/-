"""风险人工复核接口。"""
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.session import get_db
from app.models.models import AuditBatchItem, Contract, User
from app.schemas.contract import RiskStatusUpdate
from app.services import audit_log
from app.services.authorized_risks import load_authorized_risk
from app.services.audit.evidence_state import trace_object
from app.services.sign_date import read_elements

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
    db.refresh(_contract, with_for_update=True)
    if risk.audit_job_id is not None:
        job = db.get(AuditBatchItem, risk.audit_job_id)
        stale = job is None or job.audit_generation != _contract.audit_generation
    else:
        stale = bool(read_elements(_contract.elements_json).get('sign_date_invalidated_generation'))
    if stale:
        raise HTTPException(409, '签订日期或审查代次已变化，历史风险不可继续复核，请重新审查')
    comment = payload.review_comment.strip()
    if payload.review_status != "pending" and not comment:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "完成人工复核必须填写意见")
    # SQLite 不提供 FOR UPDATE 行锁；条件写同时核验快照并取得写锁，
    # 与日期确认/审查领取共享合同互斥点，阻止检查后推进代次造成旧风险写入。
    claimed = db.query(Contract).filter(
        Contract.id == _contract.id, Contract.deleted_at.is_(None),
        Contract.audit_generation == _contract.audit_generation,
        Contract.elements_json == _contract.elements_json,
        Contract.department == _contract.department,
    ).update({Contract.audit_generation: _contract.audit_generation}, synchronize_session=False)
    if claimed != 1:
        db.rollback()
        raise HTTPException(409, '签订日期或审查代次已变化，请刷新后重新复核')
    old = risk.review_status
    review = {"operator_id": user.id, "reviewed_at": datetime.now(timezone.utc).isoformat(),
              "status": payload.review_status, "reason": comment}
    try:
        risk.review_status = payload.review_status
        trace = trace_object(risk.decision_trace_json)
        trace["human_review"] = review
        risk.decision_trace_json = json.dumps(trace, ensure_ascii=False)
        audit_log.record(
            db,
            user_id=user.id,
            action="update_risk",
            target=f"risk:{risk_id}",
            detail=f"{old} -> {payload.review_status};comment={comment}",
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"risk_id": risk_id, "review_status": risk.review_status, "human_review": review}
