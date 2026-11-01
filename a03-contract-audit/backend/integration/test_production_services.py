"""显式运行的 PostgreSQL/Redis/Celery 集成验收，仅接受专用测试库。"""
import os
from threading import Event
from uuid import uuid4
from urllib.parse import urlsplit

import pytest
from celery.contrib.testing.worker import start_worker
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.models import AuditBatch, AuditBatchItem, Contract, User
from app.services.audit.window_repository import is_transient_database_error
from app.tasks import audit_tasks
from app.tasks.celery_app import celery_app


@pytest.fixture
def isolated_services(monkeypatch):
    pg_url = os.environ.get('QIJIAN_TEST_POSTGRES_URL', '')
    redis_url = os.environ.get('QIJIAN_TEST_REDIS_URL', '')
    if not pg_url or not redis_url:
        pytest.fail('未执行服务集成验收：需要显式配置 QIJIAN_TEST_POSTGRES_URL 和 QIJIAN_TEST_REDIS_URL')
    pg = make_url(pg_url)
    redis = urlsplit(redis_url)
    if pg.drivername != 'postgresql+psycopg' or not (pg.database or '').endswith('_test'):
        pytest.fail('仅允许 postgresql+psycopg 专用数据库，库名必须以 _test 结尾')
    if redis.scheme not in {'redis', 'rediss'} or not redis.path.lstrip('/').isdigit() or int(redis.path[1:]) == 0:
        pytest.fail('Redis 必须显式指定非 0 号专用测试数据库')
    schema = 'qijian_it_' + uuid4().hex
    admin = create_engine(pg_url, echo=False)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA {schema}'))
    engine = create_engine(pg_url, echo=False, connect_args={'options': f'-csearch_path={schema}'})
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        Base.metadata.create_all(engine)
        with factory.begin() as db:
            db.add(User(id=1, username='integration', password_hash='unused', role='legal'))
            db.flush()
            db.add(Contract(id=1, filename='合成.txt', storage_path='unused', uploaded_by=1, audit_generation=1))
            db.add(AuditBatch(id=1, owner_id=1, department='测试', idempotency_key=schema))
            db.flush()
            db.add(AuditBatchItem(id=1, batch_id=1, contract_id=1, filename='合成.txt', audit_generation=1, status='queued'))
        monkeypatch.setattr(audit_tasks, 'SessionLocal', factory)
        yield factory, redis_url, schema
    finally:
        engine.dispose()
        # 仅清理本次随机创建的隔离 schema；绝不清理 public 或其他数据库。
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        admin.dispose()


def test_postgres_row_lock_rejects_concurrent_claim(isolated_services):
    factory, _, _ = isolated_services
    with factory() as first, factory() as second:
        first.scalar(select(Contract).where(Contract.id == 1).with_for_update())
        with pytest.raises(DBAPIError) as error:
            second.scalar(select(Contract).where(Contract.id == 1).with_for_update(nowait=True))
        assert is_transient_database_error(error.value)
        second.rollback()
        first.rollback()
        assert second.scalar(select(Contract).where(Contract.id == 1).with_for_update(nowait=True)).id == 1


def test_redis_celery_duplicate_delivery_obeys_real_task_lease(isolated_services, monkeypatch):
    factory, redis_url, identity = isolated_services
    entered, release = Event(), Event()
    calls = []

    def synthetic_review(db, contract, **kwargs):
        calls.append(kwargs['execution_token'])
        entered.set()
        if not release.wait(timeout=15):
            raise AssertionError('集成测试未释放合成审查')
        item = db.get(AuditBatchItem, kwargs['batch_item_id'])
        item.status = 'done'
        item.execution_token = None
        item.lease_expires_at = None
        contract.status = 'done'
        db.commit()
        return {'status': 'done', 'risk_count': 0, 'cross_checks': []}

    monkeypatch.setattr(audit_tasks, 'run_audit', synthetic_review)
    # 使用实际应用任务和 Redis 传输；线程 worker 仅用于验证投递、租约和重复任务。
    old = {key: celery_app.conf.get(key) for key in (
        'broker_url', 'result_backend', 'task_default_queue', 'task_always_eager',
        'broker_transport_options', 'result_backend_transport_options')}
    celery_app.conf.update(broker_url=redis_url, result_backend=redis_url,
        task_default_queue=identity, task_always_eager=False,
        broker_transport_options={'global_keyprefix': identity},
        result_backend_transport_options={'global_keyprefix': identity})
    try:
        with start_worker(celery_app, pool='threads', concurrency=2, queues=[identity],
                          perform_ping_check=False, shutdown_timeout=20):
            first = audit_tasks.run_contract_audit.apply_async(args=[1], kwargs={'batch_item_id': 1}, queue=identity)
            assert entered.wait(timeout=10)
            duplicate = audit_tasks.run_contract_audit.apply_async(args=[1], kwargs={'batch_item_id': 1}, queue=identity)
            try:
                assert duplicate.get(timeout=10)['status'] == 'already_running'
            finally:
                release.set()
            assert first.get(timeout=10)['status'] == 'done'
            assert len(calls) == 1
            assert calls[0]
            with factory() as db:
                assert db.get(AuditBatchItem, 1).status == 'done'
            first.forget()
            duplicate.forget()
    finally:
        release.set()
        celery_app.conf.update(old)
