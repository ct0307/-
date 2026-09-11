"""权限与审计端点：权限矩阵管理 + 审计日志查询。

契约对齐前端 mock/admin.ts：
- GET  /admin/access-matrix → {modules: string[], roles: AccessRoleOut[]}（对象包裹，非裸数组）
- GET  /admin/audit-logs    → AuditLogRowOut[]（裸数组，join users 出 user/role）
固定 7 模块顺序：['工作台','合同审查','整改跟踪','多维报表','法规知识库','规则与模板','权限与审计']
"""
import json

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models.models import AccessRole, AuditLog, LLMCallLog, User
from app.schemas.contract import AccessMatrixOut, AccessRoleOut, AuditLogRowOut, LLMCallLogOut

router = APIRouter()

# 7 个模块固定顺序（与前端 ACCESS_MODULES 一一对应）
_MODULES = [
    '工作台', '合同审查', '整改跟踪', '多维报表',
    '法规知识库', '规则与模板', '权限与审计',
]


@router.get("/llm-calls", response_model=list[LLMCallLogOut])
def get_llm_calls(
    limit: int = 100,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> list[LLMCallLogOut]:
    """LLM 调用记录：最近 N 条，供可解释性展示与 OpenClaw 算力对比。"""
    logs = (
        db.query(LLMCallLog)
        .order_by(LLMCallLog.id.desc())
        .limit(limit)
        .all()
    )
    result: list[LLMCallLogOut] = []
    for l in logs:
        dt = l.created_at
        if dt and dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        time_str = dt.strftime("%Y-%m-%d %H:%M") if dt else ""
        result.append(LLMCallLogOut(
            id=f"LC{l.id:04d}",
            contract_id=l.contract_id,
            audit_job_id=l.audit_job_id,
            agent=l.agent,
            provider=l.provider,
            model=l.model,
            prompt_tokens=l.prompt_tokens,
            completion_tokens=l.completion_tokens,
            latency_ms=l.latency_ms,
            mode=l.mode,
            time=time_str,
        ))
    return result


@router.get("/access-matrix", response_model=AccessMatrixOut)
def get_access_matrix(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> AccessMatrixOut:
    """权限矩阵：返回 {modules, roles}，roles 来自 AccessRole 表（可在线编辑）。"""
    rows = db.query(AccessRole).order_by(AccessRole.id).all()
    roles = [AccessRoleOut.from_orm_row(r) for r in rows]
    return AccessMatrixOut(modules=_MODULES, roles=roles)


@router.get("/audit-logs", response_model=list[AuditLogRowOut])
def get_audit_logs(
    limit: int = 200,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> list[AuditLogRowOut]:
    """审计日志：最新 N 条，join users 出 user/role。"""
    logs = (
        db.query(AuditLog)
        .order_by(AuditLog.id.desc())
        .limit(limit)
        .all()
    )
    # 批量预取用户
    uid_set = {l.user_id for l in logs}
    users = {u.id: u for u in db.query(User).filter(User.id.in_(uid_set)).all()}

    result: list[AuditLogRowOut] = []
    for l in logs:
        u = users.get(l.user_id)
        dt = l.created_at
        if dt and dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        time_str = dt.strftime("%Y-%m-%d %H:%M") if dt else ""
        ip_val = ""
        if hasattr(l, "ip") and l.ip:
            ip_val = l.ip
        result.append(AuditLogRowOut(
            id=f"L{l.id:04d}",
            user=u.username if u else str(l.user_id),
            role=u.role if u else "",
            action=l.action,
            target=l.target or "",
            time=time_str,
            ip=ip_val,
        ))
    return result
