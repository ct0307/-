"""已授权合同的提交、接收和退回；能力声明不替代写接口授权。"""
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.api.deps import allowed_departments, get_current_user, require_department_access
from app.db.session import get_db
from app.models.models import AuditBatchItem, Contract, ContractHandoff, User
from app.services import audit_log

router = APIRouter()


class HandoffAction(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action: Literal["submit", "accept", "return"]
    expected_version: int = Field(ge=0)
    reason: str = Field(default="", max_length=500)


def _payload(contract, handoff, user, audit_job_id=None):
    state = handoff.state if handoff else "draft"
    submitter = user.role in {"business", "legal", "admin"}
    reviewer = user.role in {"legal", "admin"}
    can_review = user.role in {"legal", "finance", "admin"}
    return {"contract_id": contract.id, "filename": contract.filename, "contract_type": contract.contract_type,
            "audit_job_id": audit_job_id,
            "department": contract.department,
            "contract_status": contract.status, "state": state, "version": handoff.version if handoff else 0,
            "assigned_to": handoff.assigned_to if handoff else None,
            "reason": handoff.reason if handoff else "",
            "can_submit": submitter and state in {"draft", "returned"} and bool(contract.contract_type),
            "can_accept": reviewer and state == "submitted",
            "can_return": reviewer and state in {"submitted", "accepted"},
            "can_review": can_review,
            "review_reason_code": "ALLOWED" if can_review else "SUBMIT_TO_LEGAL"}


def _latest_completed_job(db, contract_id):
    job = db.query(AuditBatchItem).filter(AuditBatchItem.contract_id == contract_id).order_by(AuditBatchItem.id.desc()).first()
    return job.id if job and job.status in {"done", "review_required"} else None


@router.get("")
def list_handoffs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = db.query(Contract, ContractHandoff).outerjoin(ContractHandoff, ContractHandoff.contract_id == Contract.id).filter(Contract.deleted_at.is_(None))
    scope = allowed_departments(user)
    if user.role != "admin":
        query = query.filter(Contract.department.in_(scope))
    rows = query.order_by(Contract.created_at.desc(), Contract.id.desc()).all()
    latest = db.query(func.max(AuditBatchItem.id).label("id")).group_by(AuditBatchItem.contract_id).subquery()
    jobs = {job.contract_id: job.id for job in db.query(AuditBatchItem).join(latest, AuditBatchItem.id == latest.c.id)
            .filter(AuditBatchItem.contract_id.in_([c.id for c, _ in rows]),
                    AuditBatchItem.status.in_(("done", "review_required"))).all()}
    items = [_payload(contract, handoff, user, jobs.get(contract.id)) for contract, handoff in rows]
    return {"state": "NO_AUTH_SCOPE" if user.role != "admin" and not scope else "READY" if items else "NO_DATA", "items": items}


@router.get("/{contract_id}/capabilities")
def contract_capabilities(contract_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    contract = _contract(db, contract_id, user)
    audit_job_id = _latest_completed_job(db, contract_id)
    return _payload(contract, db.get(ContractHandoff, contract_id), user, audit_job_id)


def _contract(db, contract_id, user):
    contract = db.query(Contract).filter(Contract.id == contract_id, Contract.deleted_at.is_(None)).first()
    if contract is None:
        raise HTTPException(404, "合同不存在或已删除")
    require_department_access(user, contract.department)
    return contract


@router.post("/{contract_id}")
def transition_handoff(contract_id: int, payload: HandoffAction, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    contract = _contract(db, contract_id, user)
    roles = {"business", "legal", "admin"} if payload.action == "submit" else {"legal", "admin"}
    if user.role not in roles:
        raise HTTPException(403, "当前角色不能执行该交接操作")
    handoff = db.get(ContractHandoff, contract_id)
    if handoff is None:
        if payload.action != "submit" or payload.expected_version != 0:
            raise HTTPException(409, "尚未提交法务审查")
        handoff = ContractHandoff(contract_id=contract_id, state="draft", version=0)
        db.add(handoff)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(409, "交接记录已创建，请刷新后重试") from exc
    target = {"submit": "submitted", "accept": "accepted", "return": "returned"}[payload.action]
    actor = handoff.submitted_by if payload.action == "submit" else handoff.assigned_to
    if handoff.state == target and actor == user.id and handoff.version == payload.expected_version + 1:
        return _payload(contract, handoff, user, _latest_completed_job(db, contract_id))
    if handoff.version != payload.expected_version:
        raise HTTPException(409, "交接状态已变化，请刷新后重试")
    allowed = {"submit": {"draft", "returned"}, "accept": {"submitted"}, "return": {"submitted", "accepted"}}
    if handoff.state not in allowed[payload.action]:
        raise HTTPException(409, "当前状态不允许该操作")
    if payload.action == "submit" and not contract.contract_type:
        raise HTTPException(422, "请先确认合同类型")
    if payload.action == "return" and not payload.reason:
        raise HTTPException(422, "退回必须填写原因")
    values = {"state": target, "version": handoff.version + 1, "reason": payload.reason,
              "updated_at": datetime.now(timezone.utc)}
    if payload.action == "submit":
        values.update(submitted_by=user.id, assigned_to=None)
    else:
        values["assigned_to"] = user.id
    changed = db.query(ContractHandoff).filter(ContractHandoff.contract_id == contract_id, ContractHandoff.version == payload.expected_version).update(values, synchronize_session=False)
    if not changed:
        db.rollback()
        raise HTTPException(409, "交接已被其他人处理，请刷新")
    audit_log.record(db, user_id=user.id, action=f"handoff_{payload.action}", target=f"contract:{contract_id}", detail=f"{handoff.state}->{target};reason={payload.reason}")
    db.commit()
    db.refresh(handoff)
    return _payload(contract, handoff, user, _latest_completed_job(db, contract_id))
