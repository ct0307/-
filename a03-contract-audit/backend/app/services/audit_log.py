"""审计日志写入：企业追责与合规刚需。所有敏感操作调用此函数留痕。"""
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.models import AuditLog

log = get_logger("audit_log")


def record(db: Session, *, user_id: int, action: str, target: str = "", detail: str = "") -> None:
    entry = AuditLog(user_id=user_id, action=action, target=target, detail=detail)
    db.add(entry)
    db.commit()
    log.info("audit_log", user_id=user_id, action=action, target=target)
