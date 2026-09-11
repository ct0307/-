"""审查异步任务：批量合同审查在此调度。

批量场景下 API 层为每份合同派发一个此任务，前端轮询任务状态。
本地无 Redis 时可将 config.AUDIT_ASYNC=False，端点改走同步执行（共用 run_audit）。
"""
from app.core.logging import get_logger
from app.db.session import SessionLocal
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import uuid
from typing import Callable

from celery.signals import worker_ready
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.models import AuditBatchItem, Contract
from app.llm.base import LLMError
from app.services.audit.runner import StaleAuditRun, run_audit
from app.services.batch.service import retry_failed_item, transition_item
from app.tasks.celery_app import celery_app

log = get_logger("audit_task")


@dataclass(frozen=True)
class TaskErrorInfo:
    code: str
    message: str
    retryable: bool


def classify_task_error(exc: Exception) -> TaskErrorInfo:
    """把内部异常映射成可持久化、可展示的安全错误。"""
    if isinstance(exc, StaleAuditRun):
        return TaskErrorInfo("STALE_AUDIT_RUN", "审查任务已被更新的运行取代", False)
    if isinstance(exc, LLMError):
        if "超时" in str(exc):
            return TaskErrorInfo("MODEL_TIMEOUT", "模型调用超时，请稍后重试", True)
        return TaskErrorInfo("MODEL_UNAVAILABLE", "模型服务暂时不可用，请稍后重试", True)
    return TaskErrorInfo("AUDIT_INTERNAL_ERROR", "审查任务执行失败，请联系管理员", False)


def _lease_is_active(expires_at: datetime | None, now: datetime) -> bool:
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at > now


def recover_orphaned_batch_items(
    *,
    session_factory: Callable[[], Session] | None = None,
    dispatch: Callable[[int, list[str], int], object] | None = None,
) -> int:
    """重新投递未发布或租约过期的批次项；数据库行锁负责多实例去重。"""
    db = (session_factory or SessionLocal)()
    now = datetime.now(timezone.utc)
    stale_queued_before = now - timedelta(minutes=5)
    dispatch_item = dispatch or (
        lambda contract_id, dimensions, item_id: run_contract_audit.delay(contract_id, dimensions, item_id)
    )
    recovered = 0
    try:
        candidates = (
            db.query(AuditBatchItem)
            .filter(
                or_(
                    and_(
                        AuditBatchItem.status == "queued",
                        or_(
                            AuditBatchItem.task_id.is_(None),
                            AuditBatchItem.updated_at <= stale_queued_before,
                        ),
                    ),
                    and_(
                        AuditBatchItem.status.in_(("parsing", "auditing")),
                        or_(
                            AuditBatchItem.lease_expires_at.is_(None),
                            AuditBatchItem.lease_expires_at <= now,
                        ),
                    ),
                )
            )
            .order_by(AuditBatchItem.id)
            .with_for_update(skip_locked=True)
            .limit(500)
            .all()
        )
        for item in candidates:
            try:
                if item.status in {"parsing", "auditing"}:
                    item.status = "queued"
                    item.lease_expires_at = None
                    item.task_id = None
                    item.execution_token = None
                dimensions = json.loads(item.batch.dimensions_json or "[]")
                if not isinstance(dimensions, list) or not all(isinstance(value, str) for value in dimensions):
                    dimensions = []
                task = dispatch_item(item.contract_id, dimensions, item.id)
                item.task_id = str(getattr(task, "id", task))
                recovered += 1
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "audit_recovery.dispatch_failed",
                    item_id=item.id,
                    exception_type=type(exc).__name__,
                )
        db.commit()
        return recovered
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@worker_ready.connect
def _recover_items_when_worker_starts(**_kwargs) -> None:
    recovered = recover_orphaned_batch_items()
    log.info("audit_recovery.worker_ready", recovered=recovered)


@celery_app.task(name="audit.recover_orphans")
def recover_orphaned_batch_items_task() -> int:
    return recover_orphaned_batch_items()


@celery_app.task(bind=True, max_retries=3, name="audit.run_contract")
def run_contract_audit(
    self,
    contract_id: int,
    dimensions: list[str] | None = None,
    batch_item_id: int | None = None,
) -> dict:
    """单份合同审查任务：解析 → 审查 → 落库。worker 进程内自建 DB 会话。"""
    db = SessionLocal()
    execution_token: str | None = None
    try:
        item = (
            db.query(AuditBatchItem)
            .filter(AuditBatchItem.id == batch_item_id)
            .with_for_update()
            .first()
            if batch_item_id
            else None
        )
        if item and item.status == "done":
            return {"contract_id": contract_id, "status": "already_done"}
        if item:
            now = datetime.now(timezone.utc)
            if item.status in {"parsing", "auditing"} and _lease_is_active(item.lease_expires_at, now):
                db.commit()
                return {"contract_id": contract_id, "status": "already_running"}
            if item.status == "failed":
                db.commit()
                return {"contract_id": contract_id, "status": "already_failed"}
            item.status = transition_item(item.status, "parsing") if item.status == "queued" else "parsing"
            item.started_at = item.started_at or now
            item.lease_expires_at = now + timedelta(minutes=30)
            execution_token = uuid.uuid4().hex
            item.execution_token = execution_token
            db.commit()

        contract = db.query(Contract).filter(Contract.id == contract_id).first()
        if not contract:
            if item:
                item.status = "failed"
                item.error = "合同不存在"
                item.finished_at = datetime.now(timezone.utc)
                db.commit()
            return {"contract_id": contract_id, "error": "not_found"}
        if item:
            item.status = transition_item(item.status, "auditing")
            db.commit()
        result = run_audit(
            db,
            contract,
            dimensions=dimensions or [],
            generation=item.audit_generation if item else None,
            batch_item_id=item.id if item else None,
            execution_token=execution_token,
        )
        return {
            "contract_id": contract_id,
            "risk_count": result["risk_count"],
            "cross_checks": result["cross_checks"],
            "status": "done",
            "requires_review": bool(result.get("requires_review", False)),
            "ocr_confidence": result.get("ocr_confidence"),
            "review_reason": result.get("review_reason"),
        }
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        failure = classify_task_error(exc)
        log.error(
            "audit_task.failed",
            contract_id=contract_id,
            error_code=failure.code,
            exception_type=type(exc).__name__,
        )
        item = db.query(AuditBatchItem).filter(AuditBatchItem.id == batch_item_id).first() if batch_item_id else None
        if item and item.execution_token != execution_token:
            db.rollback()
            raise
        retries = int(getattr(self.request, "retries", 0))
        contract = db.query(Contract).filter(Contract.id == contract_id).first()
        persisted_attempts = item.attempts if item else retries
        should_retry = failure.retryable and max(retries, persisted_attempts) < self.max_retries
        if item:
            if item.status not in {"done", "failed"}:
                item.status = transition_item(item.status, "failed")
            item.error_code = failure.code
            item.error = failure.message
            item.lease_expires_at = None
            item.execution_token = None
            if should_retry:
                decision = retry_failed_item(item.status, attempts=item.attempts)
                item.status = decision.status
                item.attempts = decision.attempts
            else:
                item.finished_at = datetime.now(timezone.utc)
        if not should_retry and failure.code != "STALE_AUDIT_RUN" and contract:
            contract.status = "audit_failed"
        db.commit()
        if should_retry:
            raise self.retry(exc=exc, countdown=10)
        raise
    finally:
        db.close()
