"""审查异步任务：批量合同审查在此调度。

批量场景下 API 层为每份合同派发一个此任务，前端轮询任务状态。
本地无 Redis 时可将 config.AUDIT_ASYNC=False，端点改走同步执行（共用 run_audit）。
"""
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionLocal
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import time
import uuid
from typing import Callable

from celery.signals import worker_ready
from sqlalchemy import and_, exists, or_
from sqlalchemy.orm import Session

from app.models.models import AuditBatchItem, Contract, ImportBatchItem
from app.llm.base import LLMError
from app.services.audit.runner import StaleAuditRun, run_audit
from app.services.audit.window_repository import TransientPersistenceError
from app.services.batch.service import (
    ACTIVE_AUDIT_ITEM_STATUSES,
    retry_failed_item,
    transition_item,
)
from app.tasks.celery_app import celery_app
from app.tasks.import_tasks import refresh_import_batch

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
    if isinstance(exc, TransientPersistenceError):
        return TaskErrorInfo(
            "AUDIT_PERSISTENCE_UNAVAILABLE",
            "审查检查点暂时不可用，请稍后重试",
            True,
        )
    if isinstance(exc, LLMError):
        messages = {
            "MODEL_TIMEOUT": "模型调用超时，请稍后重试",
            "MODEL_UNAVAILABLE": "模型服务暂时不可用，请稍后重试",
        }
        return TaskErrorInfo(
            exc.code,
            messages.get(exc.code, "模型审查失败，请检查服务状态后重试"),
            exc.retryable,
        )
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
                        AuditBatchItem.status.in_(
                            ACTIVE_AUDIT_ITEM_STATUSES - {"queued"}
                        ),
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
                if item.status in ACTIVE_AUDIT_ITEM_STATUSES - {"queued"}:
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
    audit_deadline = time.monotonic() + settings.AUDIT_DEADLINE_SECONDS
    db = SessionLocal()
    execution_token: str | None = None
    audit_generation: int | None = None
    try:
        item = (
            db.query(AuditBatchItem)
            .filter(AuditBatchItem.id == batch_item_id)
            .with_for_update()
            .first()
            if batch_item_id
            else None
        )
        if item and item.status in {"done", "review_required"}:
            return {"contract_id": contract_id, "status": f"already_{item.status}"}
        contract = (
            db.query(Contract)
            .filter(Contract.id == contract_id)
            .with_for_update()
            .first()
        )
        if not contract:
            if item:
                item.status = "failed"
                item.error = "合同不存在"
                item.finished_at = datetime.now(timezone.utc)
                item.lease_expires_at = None
                item.execution_token = None
                _return_import_item_to_ready(db, item)
                db.commit()
            return {"contract_id": contract_id, "error": "not_found"}
        if item:
            now = datetime.now(timezone.utc)
            if item.status in ACTIVE_AUDIT_ITEM_STATUSES and _lease_is_active(
                item.lease_expires_at, now
            ):
                db.commit()
                return {"contract_id": contract_id, "status": "already_running"}
            if item.status == "failed":
                db.commit()
                return {"contract_id": contract_id, "status": "already_failed"}
            audit_generation = item.audit_generation
            if contract.audit_generation != audit_generation:
                _finalize_stale_item(
                    db,
                    item_id=item.id,
                    contract_id=contract_id,
                    audit_generation=audit_generation,
                )
                return {"contract_id": contract_id, "status": "stale"}
            item.status = transition_item(item.status, "parsing") if item.status == "queued" else "parsing"
            item.started_at = item.started_at or now
            item.lease_expires_at = now + timedelta(minutes=30)
            execution_token = uuid.uuid4().hex
            item.execution_token = execution_token
            db.flush()
            item_fence = exists().where(
                AuditBatchItem.id == item.id,
                AuditBatchItem.contract_id == contract_id,
                AuditBatchItem.audit_generation == audit_generation,
                AuditBatchItem.execution_token == execution_token,
            )
            activated = db.query(Contract).filter(
                Contract.id == contract_id,
                Contract.audit_generation == audit_generation,
                item_fence,
            ).update({Contract.status: "reviewing"}, synchronize_session=False)
            if activated != 1:
                db.rollback()
                _finalize_stale_item(
                    db,
                    item_id=item.id,
                    contract_id=contract_id,
                    audit_generation=audit_generation,
                )
                return {"contract_id": contract_id, "status": "stale"}
            db.commit()

        if item:
            promoted = db.query(AuditBatchItem).filter(
                AuditBatchItem.id == item.id,
                AuditBatchItem.contract_id == contract_id,
                AuditBatchItem.audit_generation == audit_generation,
                AuditBatchItem.execution_token == execution_token,
                AuditBatchItem.status == "parsing",
            ).update(
                {AuditBatchItem.status: "reviewing"},
                synchronize_session=False,
            )
            if promoted != 1:
                db.rollback()
                raise StaleAuditRun("审查任务 execution token 已失效")
            db.commit()
        result = run_audit(
            db,
            contract,
            dimensions=dimensions or [],
            generation=item.audit_generation if item else None,
            batch_item_id=item.id if item else None,
            execution_token=execution_token,
            deadline=audit_deadline,
        )
        if item:
            if result["status"] in {"done", "review_required"}:
                _complete_import_item(db, item)
            else:
                _return_import_item_to_ready(db, item)
            db.commit()
        return {
            "contract_id": contract_id,
            "risk_count": result["risk_count"],
            "cross_checks": result["cross_checks"],
            "status": result["status"],
            "requires_review": bool(result.get("requires_review", False)),
            "ocr_confidence": result.get("ocr_confidence"),
            "review_reason": result.get("review_reason"),
            "quality_reasons": result.get("quality_reasons", []),
            "issues": result.get("issues", []),
            "coverage": result.get("coverage", {"planned": 0, "completed": 0}),
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
        retries = int(getattr(self.request, "retries", 0))
        item = (
            db.query(AuditBatchItem)
            .filter(
                AuditBatchItem.id == batch_item_id,
                AuditBatchItem.contract_id == contract_id,
            )
            .populate_existing()
            .first()
            if batch_item_id
            else None
        )
        persisted_attempts = item.attempts if item else retries
        failure_status = item.status if item else None
        failure_attempts = item.attempts if item else retries
        if item and failure_status not in {"done", "review_required", "failed"}:
            failure_status = (
                "failed"
                if failure_status == "auditing"
                else transition_item(failure_status, "failed")
            )
        should_retry = failure.retryable and max(retries, persisted_attempts) < self.max_retries
        if batch_item_id:
            if item is None or audit_generation is None or not execution_token:
                db.rollback()
                raise
            values = {
                AuditBatchItem.status: failure_status,
                AuditBatchItem.error_code: failure.code,
                AuditBatchItem.error: failure.message,
                AuditBatchItem.lease_expires_at: None,
                AuditBatchItem.execution_token: None,
            }
            if should_retry:
                decision = retry_failed_item(failure_status, attempts=failure_attempts)
                values[AuditBatchItem.status] = decision.status
                values[AuditBatchItem.attempts] = decision.attempts
            else:
                values[AuditBatchItem.finished_at] = datetime.now(timezone.utc)

            contract_fence = db.query(Contract).filter(
                Contract.id == contract_id,
                Contract.audit_generation == audit_generation,
            ).update(
                {Contract.audit_generation: Contract.audit_generation},
                synchronize_session=False,
            )
            contract_generation_matches = exists().where(
                Contract.id == contract_id,
                Contract.audit_generation == audit_generation,
            )
            published = db.query(AuditBatchItem).filter(
                AuditBatchItem.id == batch_item_id,
                AuditBatchItem.contract_id == contract_id,
                AuditBatchItem.audit_generation == audit_generation,
                AuditBatchItem.execution_token == execution_token,
                contract_generation_matches,
            ).update(values, synchronize_session=False)
            if contract_fence != 1 or published != 1:
                db.rollback()
                raise
            if not should_retry:
                _return_import_item_to_ready(db, item)

        if not should_retry and failure.code != "STALE_AUDIT_RUN":
            contract_updated = db.query(Contract).filter(
                Contract.id == contract_id,
                *(
                    [Contract.audit_generation == audit_generation]
                    if batch_item_id
                    else []
                ),
            ).update({Contract.status: "audit_failed"}, synchronize_session=False)
            if batch_item_id and contract_updated != 1:
                db.rollback()
                raise
        db.commit()
        if should_retry:
            raise self.retry(exc=exc, countdown=10)
        raise
    finally:
        db.close()


def _finalize_stale_item(
    db: Session,
    *,
    item_id: int,
    contract_id: int,
    audit_generation: int,
) -> None:
    """用一次性 token 终结陈旧任务，不触碰合同当前代次。"""
    db.rollback()
    stale_token = uuid.uuid4().hex
    claimed = db.query(AuditBatchItem).filter(
        AuditBatchItem.id == item_id,
        AuditBatchItem.contract_id == contract_id,
        AuditBatchItem.audit_generation == audit_generation,
        AuditBatchItem.status.notin_({"done", "review_required", "failed"}),
    ).update(
        {
            AuditBatchItem.execution_token: stale_token,
            AuditBatchItem.lease_expires_at: None,
        },
        synchronize_session=False,
    )
    if claimed != 1:
        db.rollback()
        return
    stale_item = (
        db.query(AuditBatchItem)
        .filter(
            AuditBatchItem.id == item_id,
            AuditBatchItem.contract_id == contract_id,
            AuditBatchItem.execution_token == stale_token,
        )
        .populate_existing()
        .one()
    )
    _return_import_item_to_ready(db, stale_item)
    finalized = db.query(AuditBatchItem).filter(
        AuditBatchItem.id == item_id,
        AuditBatchItem.execution_token == stale_token,
    ).update(
        {
            AuditBatchItem.status: "failed",
            AuditBatchItem.error_code: "STALE_AUDIT_RUN",
            AuditBatchItem.error: "审查任务已被更新的运行取代",
            AuditBatchItem.execution_token: None,
            AuditBatchItem.lease_expires_at: None,
            AuditBatchItem.finished_at: datetime.now(timezone.utc),
        },
        synchronize_session=False,
    )
    if finalized != 1:
        db.rollback()
        return
    db.commit()


def _complete_import_item(db: Session, item: AuditBatchItem) -> None:
    if item.import_item_id is None:
        return
    source_item = db.get(ImportBatchItem, item.import_item_id)
    if source_item is None:
        return
    source_item.status = "done"
    refresh_import_batch(source_item.batch)


def _return_import_item_to_ready(db: Session, item: AuditBatchItem) -> None:
    if item.import_item_id is None:
        return
    source_item = db.get(ImportBatchItem, item.import_item_id)
    if source_item is None or source_item.status != "auditing":
        return
    source_item.status = "ready"
    refresh_import_batch(source_item.batch)
