"""审计日志写入：企业追责与合规刚需。所有敏感操作调用此函数留痕。"""
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.models import AuditLog

log = get_logger("audit_log")


def record(
    db: Session,
    *,
    user_id: int,
    action: str,
    target: str = "",
    detail: str = "",
    ip: str = "",
) -> None:
    """记录审计日志。ip 从调用方按需传入（auth/合同操作等），其余内部操作留空。"""
    entry = AuditLog(user_id=user_id, action=action, target=target, detail=detail, ip=ip)
    db.add(entry)
    db.commit()
    log.info("audit_log", user_id=user_id, action=action, target=target, ip=ip or "-")
