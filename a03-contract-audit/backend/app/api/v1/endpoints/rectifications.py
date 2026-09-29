"""整改跟踪端点：整改项的列表 / 新建 / 状态流转。

契约对齐前端 stores/rectify.ts：
- GET  /rectifications        → RectificationOut[]（裸数组，最新在前）
- POST /rectifications        → 新建，返回带 id 的 RectificationOut
- PATCH /rectifications/{id}  → 改 status，{id} 为 RC001 形态字符串
level 英文（high/medium/low），status 按待处理→处理中→待复核→已闭环流转。
"""
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import allowed_departments, require_roles
from app.db.session import get_db
from app.models.models import Contract, Risk, Rectification, User
from app.services.authorized_risks import load_authorized_risk
from app.schemas.contract import (
    RectificationCreate,
    RectificationOut,
    RectificationStatusUpdate,
)
from app.services import audit_log

router = APIRouter()

_VALID_STATUS = {"待处理", "处理中", "待复核", "已闭环"}
_VALID_LEVEL = {"high", "medium", "low"}
_ALLOWED_TRANSITIONS = {
    "待处理": {"处理中"},
    "处理中": {"待复核"},
    "待复核": {"处理中", "已闭环"},
    "已闭环": {"待处理"},
}


def _parse_id(rc_id: str) -> int:
    """RC001 → 1；纯数字也兼容。非法则 400。"""
    raw = rc_id[2:] if rc_id.upper().startswith("RC") else rc_id
    try:
        return int(raw)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"非法整改项 ID: {rc_id}")


@router.get("", response_model=list[RectificationOut])
def list_rectifications(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("legal", "finance", "business")),
) -> list[RectificationOut]:
    query = db.query(Rectification)
    if user.role != "admin":
        query = query.join(Risk, Rectification.risk_id == Risk.id).join(Contract, Risk.contract_id == Contract.id).filter(
            Contract.deleted_at.is_(None), Contract.department.in_(allowed_departments(user)),
        )
    rows = query.order_by(Rectification.id.desc()).all()
    return [RectificationOut.from_orm_row(r) for r in rows]


@router.post("", response_model=RectificationOut)
def create_rectification(
    payload: RectificationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("legal", "finance")),
) -> RectificationOut:
    if payload.level not in _VALID_LEVEL:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"非法风险等级: {payload.level}")
    if payload.status != "待处理":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "新整改项必须从“待处理”开始")
    if payload.risk_id is None:
        raise HTTPException(422, "整改必须关联已授权的风险项")
    risk, contract = load_authorized_risk(db, payload.risk_id, user)
    if risk.review_status not in {"confirmed", "to_modify"}:
        raise HTTPException(409, "请先复核风险再创建整改任务")
    created = payload.created or date.today().isoformat()
    due = payload.due or (date.today() + timedelta(days=7)).isoformat()
    try:
        if date.fromisoformat(due) < date.fromisoformat(created):
            raise ValueError()
    except ValueError:
        raise HTTPException(422, "日期格式应为 YYYY-MM-DD，截止日不得早于创建日")
    row = Rectification(
        contract=contract.filename,
        risk=risk.category,
        level=risk.level,
        owner=payload.owner,
        status=payload.status,
        created=created,
        due=due,
        note=payload.note,
        risk_id=payload.risk_id,
    )
    db.add(row)
    db.flush()
    audit_log.record(
        db, user_id=user.id, action="create_rectification",
        target=f"rectification:{row.id}", detail=f"{payload.contract} · {payload.risk}",
    )
    db.commit()
    db.refresh(row)
    return RectificationOut.from_orm_row(row)


@router.patch("/{rc_id}", response_model=RectificationOut)
def update_rectification_status(
    rc_id: str,
    payload: RectificationStatusUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("legal", "finance", "business")),
) -> RectificationOut:
    if payload.status not in _VALID_STATUS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"非法状态: {payload.status}")
    pk = _parse_id(rc_id)
    row = db.query(Rectification).filter(Rectification.id == pk).first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "整改项不存在")
    if row.risk_id is None:
        if user.role != "admin":
            raise HTTPException(403, "历史整改缺少合同归属，请管理员核验")
    else:
        load_authorized_risk(db, row.risk_id, user)
    if user.role == "business" and (row.owner != user.username or row.status not in {"待处理", "处理中"} or payload.status not in {"处理中", "待复核"}):
        raise HTTPException(403, "业务人员仅可办理本人整改并提交复核")
    old = row.status
    if payload.status not in _ALLOWED_TRANSITIONS.get(old, set()):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"不允许从“{old}”直接流转到“{payload.status}”",
        )
    resolution = (payload.resolution if payload.resolution is not None else row.resolution).strip()
    review_comment = (
        payload.review_comment if payload.review_comment is not None else row.review_comment
    ).strip()
    if payload.status == "待复核" and not resolution:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "请先填写整改结果再提交复核")
    if old == "待复核" and not review_comment:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "复核通过或退回时必须填写复核意见")
    now = datetime.now(timezone.utc)
    row.status = payload.status
    row.resolution = resolution
    row.review_comment = review_comment
    if payload.status == "待复核":
        row.submitted_at = now
    elif payload.status == "已闭环":
        row.closed_at = now
    elif payload.status in {"待处理", "处理中"}:
        row.closed_at = None
    audit_log.record(
        db, user_id=user.id, action="update_rectification",
        target=f"rectification:{row.id}", detail=f"{old} -> {payload.status}",
    )
    db.commit()
    db.refresh(row)
    return RectificationOut.from_orm_row(row)
