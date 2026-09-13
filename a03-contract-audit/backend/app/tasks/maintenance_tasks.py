"""数据生命周期维护任务。"""

from datetime import datetime, timezone

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.imports.trash import purge_expired_contract_files
from app.tasks.celery_app import celery_app


@celery_app.task(name="maintenance.purge_contract_trash")
def purge_contract_trash() -> dict[str, int]:
    db = SessionLocal()
    try:
        purged = purge_expired_contract_files(
            db,
            storage_root=settings.storage_path,
            retention_days=settings.CONTRACT_TRASH_RETENTION_DAYS,
            now=datetime.now(timezone.utc),
        )
        return {"purged": purged}
    finally:
        db.close()
