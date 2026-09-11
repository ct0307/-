"""规则与模板端点：审查规则库 + 合同模板库的 CRUD。

契约对齐前端 api/rules.ts（MOCK_ENABLED.rules 关时走此处）：
- GET  /rules              → AuditRuleOut[]（裸数组）
- POST /rules              → 新建规则，builtin=False
- DELETE /rules/{id}       → 删除，{id} 为 R02 形态字符串
- GET  /templates          → ContractTemplateOut[]
- POST /templates          → 新建模板
- DELETE /templates/{id}   → 删除，{id} 为 T02 形态字符串
"""
import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.session import get_db
from app.models.models import AuditRule, ContractTemplate, User
from app.schemas.contract import (
    AuditRuleCreate,
    AuditRuleOut,
    ContractTemplateCreate,
    ContractTemplateOut,
)
from app.services import audit_log

router = APIRouter()

_VALID_LEVEL = {"high", "medium", "low"}


def _parse_id(prefix: str, raw: str) -> int:
    """R02 / T02 → 数字 PK；纯数字也兼容。"""
    s = raw[len(prefix):] if raw.upper().startswith(prefix.upper()) else raw
    try:
        return int(s)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"非法 ID: {raw}")


# ──────────────── 审查规则 ────────────────

@router.get("/rules", response_model=list[AuditRuleOut])
def list_rules(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("legal", "finance", "business")),
) -> list[AuditRuleOut]:
    rows = db.query(AuditRule).order_by(AuditRule.id).all()
    return [AuditRuleOut.from_orm_row(r) for r in rows]


@router.post("/rules", response_model=AuditRuleOut)
def create_rule(
    payload: AuditRuleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> AuditRuleOut:
    if payload.level not in _VALID_LEVEL:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"非法等级: {payload.level}")
    row = AuditRule(
        name=payload.name,
        dimension=payload.dimension,
        level=payload.level,
        agent=payload.agent,
        desc=payload.desc,
        builtin=False,
    )
    db.add(row)
    db.flush()
    audit_log.record(db, user_id=user.id, action="create_rule", target=f"rule:{row.id}", detail=payload.name)
    db.commit()
    db.refresh(row)
    return AuditRuleOut.from_orm_row(row)


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(
    rule_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> None:
    pk = _parse_id("R", rule_id)
    row = db.query(AuditRule).filter(AuditRule.id == pk).first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "规则不存在")
    if row.builtin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "内置规则不可删除")
    db.delete(row)
    audit_log.record(db, user_id=user.id, action="delete_rule", target=f"rule:{pk}", detail=row.name)
    db.commit()


# ──────────────── 合同模板 ────────────────

@router.get("/templates", response_model=list[ContractTemplateOut])
def list_templates(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("legal", "finance", "business")),
) -> list[ContractTemplateOut]:
    rows = db.query(ContractTemplate).order_by(ContractTemplate.id).all()
    return [ContractTemplateOut.from_orm_row(r) for r in rows]


@router.post("/templates", response_model=ContractTemplateOut)
def create_template(
    payload: ContractTemplateCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> ContractTemplateOut:
    row = ContractTemplate(
        name=payload.name,
        type=payload.type,
        clauses=json.dumps(payload.clauses, ensure_ascii=False),
        builtin=False,
    )
    db.add(row)
    db.flush()
    audit_log.record(db, user_id=user.id, action="create_template", target=f"template:{row.id}", detail=payload.name)
    db.commit()
    db.refresh(row)
    return ContractTemplateOut.from_orm_row(row)


@router.delete("/templates/{tpl_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    tpl_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> None:
    pk = _parse_id("T", tpl_id)
    row = db.query(ContractTemplate).filter(ContractTemplate.id == pk).first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "模板不存在")
    if row.builtin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "内置模板不可删除")
    db.delete(row)
    audit_log.record(db, user_id=user.id, action="delete_template", target=f"template:{pk}", detail=row.name)
    db.commit()
