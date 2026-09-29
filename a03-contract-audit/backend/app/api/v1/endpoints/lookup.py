"""下拉选项配置端点：业务部门 / 合同类型由管理员维护。

契约：
- GET  /admin/lookups/{category}  → LookupItemOut[]（所有已登录角色可读，供前端下拉框使用）
- POST /admin/lookups              → 新增条目（admin 专属）
- DELETE /admin/lookups/{id}       → 删除条目（admin 专属）
"""
import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models.models import ContractTypeProfile, LookupItem, User
from app.schemas.contract import (
    ContractTypeProfileOut,
    ContractTypeProfileUpdate,
    LookupItemCreate,
    LookupItemOut,
)
from app.services import audit_log
from app.services.imports.type_profiles import (
    ProfileNotFound,
    ProfileVersionConflict,
    TypeProfile,
    load_profile_rows,
    normalize_terms,
    update_profile,
)

router = APIRouter()

_VALID_CATEGORIES = {"department", "contract_type"}


def _require_admin_user(user: User) -> None:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权访问此资源")


def _profile_out(
    lookup_item: LookupItem,
    profile: ContractTypeProfile,
) -> ContractTypeProfileOut:
    runtime_profile = TypeProfile(
        aliases=normalize_terms(json.loads(profile.aliases_json)),
        positive_signals=normalize_terms(json.loads(profile.positive_signals_json)),
        negative_signals=normalize_terms(json.loads(profile.negative_signals_json)),
    )
    return ContractTypeProfileOut(
        lookup_item_id=lookup_item.id,
        value=lookup_item.value,
        aliases=list(runtime_profile.aliases),
        positive_signals=list(runtime_profile.positive_signals),
        negative_signals=list(runtime_profile.negative_signals),
        enabled=profile.enabled,
        version=profile.version,
    )


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


@router.get(
    "/lookups/contract_type/profiles",
    response_model=list[ContractTypeProfileOut],
)
def list_contract_type_profiles(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
) -> list[ContractTypeProfileOut]:
    _require_admin_user(current_user)
    return [_profile_out(item, profile) for item, profile in load_profile_rows(db)]


@router.post("/lookups", response_model=LookupItemOut, status_code=status.HTTP_201_CREATED)
def create_lookup(
    body: LookupItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
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
    if body.category == "contract_type":
        item.contract_type_profile = ContractTypeProfile()
    db.add(item)
    db.flush()
    audit_log.record(
        db,
        user_id=current_user.id,
        action="lookup_create",
        target=body.category,
        detail=body.value,
    )
    db.commit()
    db.refresh(item)
    return LookupItemOut(id=item.id, category=item.category, value=item.value, sort_order=item.sort_order)


@router.put(
    "/lookups/{item_id}/profile",
    response_model=ContractTypeProfileOut,
)
def update_contract_type_profile(
    item_id: int,
    body: ContractTypeProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
) -> ContractTypeProfileOut:
    _require_admin_user(current_user)
    try:
        item, profile = update_profile(
            db,
            item_id=item_id,
            expected_version=body.version,
            aliases=body.aliases,
            positive_signals=body.positive_signals,
            negative_signals=body.negative_signals,
            enabled=body.enabled,
        )
    except ProfileNotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "合同类型规则不存在") from error
    except ProfileVersionConflict as error:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "规则已被更新，请刷新后重试",
        ) from error
    except ValueError as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            str(error),
        ) from error

    normalized = _profile_out(item, profile)
    audit_log.record(
        db,
        user_id=current_user.id,
        action="contract_type_profile_update",
        target=f"lookup:{item_id}",
        detail=json.dumps(
            {
                "lookup_item_id": item_id,
                "version": normalized.version,
                "aliases_count": len(normalized.aliases),
                "positive_signals_count": len(normalized.positive_signals),
                "negative_signals_count": len(normalized.negative_signals),
                "enabled": normalized.enabled,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    )
    db.commit()
    return normalized


@router.delete("/lookups/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lookup(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
):
    item = db.get(LookupItem, item_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "条目不存在")
    audit_log.record(
        db,
        user_id=current_user.id,
        action="lookup_delete",
        target=item.category,
        detail=item.value,
    )
    db.delete(item)
    db.commit()
