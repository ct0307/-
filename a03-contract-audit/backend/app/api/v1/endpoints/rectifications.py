"""整改跟踪端点：整改项的列表 / 新建 / 状态流转。

契约对齐前端 stores/rectify.ts：
- GET  /rectifications        → RectificationOut[]（裸数组，最新在前）
- POST /rectifications        → 新建，返回带 id 的 RectificationOut
- PATCH /rectifications/{id}  → 改 status，{id} 为 RC001 形态字符串
level 英文（high/medium/low）、status 中文（待处理/处理中/已闭环），逐字段按前端现值返回。
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.session import get_db
from app.models.models import Rectification, User
from app.schemas.contract import (
    RectificationCreate,
    RectificationOut,
    RectificationStatusUpdate,
)
from app.services import audit_log

router = APIRouter()

_VALID_STATUS = {"待处理", "处理中", "已闭环"}
_VALID_LEVEL = {"high", "medium", "low"}


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
    rows = db.query(Rectification).order_by(Rectification.id.desc()).all()
    return [RectificationOut.from_orm_row(r) for r in rows]


@router.post("", response_model=RectificationOut)
def create_rectification(
    payload: RectificationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("legal", "finance")),
) -> RectificationOut:
    if payload.level not in _VALID_LEVEL:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"非法风险等级: {payload.level}")
    if payload.status not in _VALID_STATUS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"非法状态: {payload.status}")
    created = payload.created or date.today().isoformat()
    due = payload.due or (date.today() + timedelta(days=7)).isoformat()
    row = Rectification(
        contract=payload.contract,
        risk=payload.risk,
        level=payload.level,
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
    user: User = Depends(require_roles("legal", "finance")),
) -> RectificationOut:
    if payload.status not in _VALID_STATUS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"非法状态: {payload.status}")
    pk = _parse_id(rc_id)
    row = db.query(Rectification).filter(Rectification.id == pk).first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "整改项不存在")
    old = row.status
    row.status = payload.status
    audit_log.record(
        db, user_id=user.id, action="update_rectification",
        target=f"rectification:{row.id}", detail=f"{old} -> {payload.status}",
    )
    db.commit()
    db.refresh(row)
    return RectificationOut.from_orm_row(row)
