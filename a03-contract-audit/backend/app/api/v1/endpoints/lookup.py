"""下拉选项配置端点：业务部门 / 合同类型由管理员维护。

契约：
- GET  /admin/lookups/{category}  → LookupItemOut[]（所有已登录角色可读，供前端下拉框使用）
- POST /admin/lookups              → 新增条目（admin 专属）
- DELETE /admin/lookups/{id}       → 删除条目（admin 专属）
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models.models import LookupItem, User
from app.schemas.contract import LookupItemCreate, LookupItemOut
from app.services import audit_log

router = APIRouter()

_VALID_CATEGORIES = {"department", "contract_type"}


@router.get("/lookups/{category}", response_model=list[LookupItemOut])
def list_lookups(
    category: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),   # 所有已登录角色可读
):
    if category not in _VALID_CATEGORIES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"非法 category: {category}")
    items = (
        db.query(LookupItem)
        .filter(LookupItem.category == category)
        .order_by(LookupItem.sort_order, LookupItem.id)
        .all()
    )
    return [LookupItemOut(id=i.id, category=i.category, value=i.value, sort_order=i.sort_order) for i in items]


@router.post("/lookups", response_model=LookupItemOut, status_code=status.HTTP_201_CREATED)
def create_lookup(
    body: LookupItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin"])),
):
    if body.category not in _VALID_CATEGORIES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"非法 category: {body.category}")
    # 同一 category 内不允许重复值
    exists = db.query(LookupItem).filter(
        LookupItem.category == body.category,
        LookupItem.value == body.value,
    ).first()
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, f"已存在：{body.value}")

    item = LookupItem(category=body.category, value=body.value, sort_order=body.sort_order)
    db.add(item)
    db.commit()
    db.refresh(item)
    audit_log.record(db, current_user.id, "lookup_create", body.category, body.value)
    return LookupItemOut(id=item.id, category=item.category, value=item.value, sort_order=item.sort_order)


@router.delete("/lookups/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lookup(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["admin"])),
):
    item = db.get(LookupItem, item_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "条目不存在")
    audit_log.record(db, current_user.id, "lookup_delete", item.category, item.value)
    db.delete(item)
    db.commit()
