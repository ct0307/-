"""审查异步任务：批量合同审查在此调度。

批量场景下 API 层为每份合同派发一个此任务，前端轮询任务状态。
本地无 Redis 时可将 config.AUDIT_ASYNC=False，端点改走同步执行（共用 run_audit）。
"""
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.models.models import Contract
from app.services.audit.runner import run_audit
from app.tasks.celery_app import celery_app

log = get_logger("audit_task")


@celery_app.task(bind=True, max_retries=3, name="audit.run_contract")
def run_contract_audit(self, contract_id: int) -> dict:
    """单份合同审查任务：解析 → 审查 → 落库。worker 进程内自建 DB 会话。"""
    db = SessionLocal()
    try:
        contract = db.query(Contract).filter(Contract.id == contract_id).first()
        if not contract:
            return {"contract_id": contract_id, "error": "not_found"}
        count = run_audit(db, contract)
        return {"contract_id": contract_id, "risk_count": count, "status": "done"}
    except Exception as exc:  # noqa: BLE001
        log.error("audit_task.failed", contract_id=contract_id, error=str(exc))
        raise self.retry(exc=exc, countdown=10)
    finally:
        db.close()
