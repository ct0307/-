"""审查任务派发 Adapter：生产 Celery，本地受限线程池。"""
from concurrent.futures import ThreadPoolExecutor
import uuid
from typing import Callable
import time

from celery.exceptions import Retry

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.models import AuditBatchItem

_local_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="audit-local")
_sleep = time.sleep


def _run_local(contract_id: int, dimensions: list[str], item_id: int) -> None:
    from app.tasks.audit_tasks import run_contract_audit

    for attempt in range(4):
        try:
            run_contract_audit.run(contract_id, dimensions, item_id)
            return
        except Retry:
            if attempt == 3:
                raise
            _sleep(min(2 ** attempt, 10))


def dispatch_audit_ids(contract_id: int, dimensions: list[str], item_id: int) -> str:
    """按持久标识派发任务，供新任务和恢复扫描共用。"""
    if settings.AUDIT_ASYNC:
        from app.tasks.audit_tasks import run_contract_audit

        task = run_contract_audit.delay(contract_id, dimensions, item_id)
        return str(task.id)

    task_id = f"local:{uuid.uuid4().hex}"
    _local_executor.submit(_run_local, contract_id, list(dimensions), item_id)
    return task_id


def dispatch_audit_item(item: AuditBatchItem, dimensions: list[str]) -> str:
    """派发已提交的持久任务并返回执行器任务标识。"""
    return dispatch_audit_ids(item.contract_id, dimensions, item.id)


def dispatch_import_item(item_id: int) -> str:
    """按持久导入项标识派发解析任务。"""
    if settings.AUDIT_ASYNC:
        from app.tasks.import_tasks import parse_import_item

        task = parse_import_item.delay(item_id)
        return str(task.id)

    task_id = f"local-import:{uuid.uuid4().hex}"

    def run() -> None:
        from app.tasks.import_tasks import parse_import_item

        parse_import_item.run(item_id)

    _local_executor.submit(run)
    return task_id


def recover_local_audit_items(
    *,
    session_factory: Callable = SessionLocal,
    dispatch: Callable[[int, list[str], int], str] = dispatch_audit_ids,
) -> int:
    """重置旧进程的本地任务，再通过统一孤儿扫描重新派发。"""
    db = session_factory()
    try:
        stale_items = (
            db.query(AuditBatchItem)
            .filter(
                AuditBatchItem.task_id.like("local:%"),
                AuditBatchItem.status.in_(("queued", "parsing", "auditing")),
            )
            .with_for_update()
            .all()
        )
        for item in stale_items:
            item.status = "queued"
            item.task_id = None
            item.lease_expires_at = None
            item.execution_token = None
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    from app.tasks.audit_tasks import recover_orphaned_batch_items

    return recover_orphaned_batch_items(
        session_factory=session_factory,
        dispatch=dispatch,
    )


def shutdown_local_dispatcher() -> None:
    _local_executor.shutdown(wait=False, cancel_futures=False)
