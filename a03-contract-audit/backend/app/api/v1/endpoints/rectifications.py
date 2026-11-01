"""整改端点；所有修改委托集中工作流完成权限、版本与事件校验。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.api.deps import allowed_departments, require_roles
from app.db.session import get_db
from app.models.models import Contract, Risk, Rectification, User
from app.schemas.contract import RectificationCreate, RectificationOut, RectificationStatusUpdate, RectificationPlanUpdate, RectificationEscalate
from app.services import audit_log, rectification_workflow as workflow
from app.services.authorized_risks import load_authorized_risk

router = APIRouter()

@router.get('', response_model=list[RectificationOut])
def list_rectifications(db: Session = Depends(get_db), user: User = Depends(require_roles('legal','finance','business'))):
    query = db.query(Rectification)
    if user.role != 'admin':
        query = query.join(Risk, Rectification.risk_id == Risk.id).join(Contract, Risk.contract_id == Contract.id).filter(Contract.deleted_at.is_(None), Contract.department.in_(allowed_departments(user)))
    else:
        # 管理员可以核验无归属旧记录，但已删除合同不再作为可办理来源。
        query = query.outerjoin(Risk, Rectification.risk_id == Risk.id).outerjoin(Contract, Risk.contract_id == Contract.id).filter((Rectification.risk_id.is_(None)) | Contract.deleted_at.is_(None))
    return [workflow.output(db, row, user) for row in query.order_by(Rectification.id.desc()).all()]

@router.get('/participants')
def list_participants(risk_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles('legal','finance','business'))):
    _, contract = load_authorized_risk(db, risk_id, user)
    return [dict(id=p.id,username=p.username,role=p.role,department=p.department) for p in db.query(User).order_by(User.username).all() if workflow.eligible(p, contract)]

@router.get('/materials')
def list_materials(risk_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles('legal','finance','business'))):
    _, contract = load_authorized_risk(db, risk_id, user)
    query = db.query(Contract).filter(Contract.deleted_at.is_(None),Contract.id != contract.id,Contract.department == contract.department)
    return [dict(id=m.id,filename=m.filename,content_sha256=m.content_sha256) for m in query.order_by(Contract.id.desc()).all()]

@router.post('', response_model=RectificationOut)
def create_rectification(payload: RectificationCreate, db: Session = Depends(get_db), user: User = Depends(require_roles('legal','finance'))):
    return workflow.create(db,payload,user)

@router.patch('/{rc_id}/plan', response_model=RectificationOut)
def update_rectification_plan(rc_id: str, payload: RectificationPlanUpdate, db: Session = Depends(get_db), user: User = Depends(require_roles('legal','finance'))):
    return workflow.update_plan(db,rc_id,payload,user)

@router.post('/{rc_id}/escalate', response_model=RectificationOut)
def escalate_rectification(rc_id: str, payload: RectificationEscalate, db: Session = Depends(get_db), user: User = Depends(require_roles('legal','finance','business'))):
    return workflow.escalate(db,rc_id,payload,user)

@router.patch('/{rc_id}', response_model=RectificationOut)
def update_rectification_status(rc_id: str, payload: RectificationStatusUpdate, db: Session = Depends(get_db), user: User = Depends(require_roles('legal','finance','business'))):
    return workflow.transition(db,rc_id,payload,user)
