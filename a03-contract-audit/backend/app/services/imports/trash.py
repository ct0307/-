"""合同回收站生命周期服务。"""

from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.models import Contract


def purge_expired_contract_files(
    db: Session,
    *,
    storage_root: str,
    retention_days: int,
    now: datetime,
) -> int:
    """清理超过保留期的受管合同文件。"""
    root = Path(storage_root).resolve()
    cutoff = now - timedelta(days=retention_days)
    expired = db.query(Contract).filter(
        Contract.deleted_at.is_not(None),
        Contract.deleted_at <= cutoff,
        Contract.storage_path != "",
    ).all()
    purged = 0
    for contract in expired:
        path = Path(contract.storage_path).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            continue
        if path.is_file():
            path.unlink()
        contract.storage_path = ""
        contract.status = "purged"
        purged += 1
    db.commit()
    return purged
