"""Celery 应用：企业级批量审查、长任务、失败重试、任务可观测。"""
from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "a03",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks.audit_tasks", "app.tasks.import_tasks", "app.tasks.maintenance_tasks"],
)

celery_app.conf.update(
    task_track_started=True,
    task_time_limit=1800,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    timezone="Asia/Shanghai",
    beat_schedule={
        "recover-orphaned-audit-items": {
            "task": "audit.recover_orphans",
            "schedule": 60.0,
        },
        "purge-expired-contract-trash": {
            "task": "maintenance.purge_contract_trash",
            "schedule": 86400.0,
        },
    },
)
