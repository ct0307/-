"""风险、整改、追问共用的合同归属授权边界。"""
from fastapi import HTTPException
from app.api.deps import require_department_access
from app.models.models import Contract, Risk


def load_authorized_risk(db, risk_id, user):
    risk = db.query(Risk).filter(Risk.id == risk_id).first()
    if risk is None:
        raise HTTPException(404, "风险项不存在")
    contract = db.query(Contract).filter(Contract.id == risk.contract_id, Contract.deleted_at.is_(None)).first()
    if contract is None:
        raise HTTPException(404, "合同不存在或已删除")
    require_department_access(user, contract.department)
    return risk, contract
