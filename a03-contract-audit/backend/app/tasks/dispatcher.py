"""审查任务派发 Adapter：生产 Celery，本地受限线程池。"""
from concurrent.futures import ThreadPoolExecutor
import uuid
from typing import Callable
import time

from celery.exceptions import Retry

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.models import AuditBatchItem, ImportBatchItem

_local_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="audit-local")
# 导入解析与审查任务解耦：解析走独立线程池，避免上一轮审查占用单线程时
# 新上传的合同一直卡在"等待解析"队列里。
_import_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="import-parse")
_sleep = time.sleep


def _run_local(contract_id: int, dimensions: list[str], item_id: int) -> None:
    from app.tasks.audit_tasks import run_contract_audit

    for attempt in range(4):
        # 模拟 eager 执行上下文，使真实 retry 只抛信号而不投递消息队列。
        run_contract_audit.push_request(
            called_directly=False, is_eager=True, retries=attempt,
            args=(contract_id, dimensions, item_id), kwargs={},
        )
        try:
            run_contract_audit.run(contract_id, dimensions, item_id)
            return
        except Retry:
            if attempt == 3:
                raise
            _sleep(min(2 ** attempt, 10))
        finally:
            run_contract_audit.pop_request()


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

    _import_executor.submit(run)
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
                AuditBatchItem.status.in_(
                    ("queued", "parsing", "reviewing", "validating", "auditing")
                ),
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
    _import_executor.shutdown(wait=False, cancel_futures=False)


def recover_local_import_items(
    *,
    session_factory: Callable = SessionLocal,
    dispatch: Callable[[int], str] = dispatch_import_item,
) -> int:
    """仅在本地单进程启动时恢复旧队列；不可用于运行中的定时扫描。"""
    db = session_factory()
    recovered = 0
    try:
        # 重启后旧线程已不存在，即使刚开始解析也必须恢复。
        # 固定待恢复 ID 快照，不截断为 500 项，也不反复扫描仍为 queued 的项。
        candidates = (
            db.query(ImportBatchItem.id)
            .filter(ImportBatchItem.status.in_(("queued", "parsing")))
            .order_by(ImportBatchItem.id)
            .all()
        )
        for (item_id,) in candidates:
            item = db.get(ImportBatchItem, item_id)
            if item is None or item.status not in {"queued", "parsing"}:
                continue
            item.status = "queued"
            item.attempts = max(item.attempts, 0)
            db.commit()
            try:
                dispatch(item.id)
                recovered += 1
            except Exception:
                item.status = "queued"
                item.error_code = "DISPATCH_PENDING"
                item.error_message = "文件已保存，正在等待重新解析"
                db.commit()
        return recovered
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
