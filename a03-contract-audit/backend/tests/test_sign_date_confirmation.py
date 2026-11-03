"""签订日期确认使用真实路由和数据库，覆盖权限、失效及重解析。"""
import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user
from app.api.v1.endpoints import contracts
from app.api.v1.endpoints import risks as risks_endpoint
from app.db.session import Base, get_db
from app.core.crypto import encrypt_bytes
from app.models.models import AuditBatch, AuditBatchItem, AuditLog, AuditWorkflow, Contract, ContractClause, ImportBatch, ImportBatchItem, Risk, User
from app.services.audit.finalization import workflow_view
from app.services.audit.evidence_state import evidence_validation_mode
from app.services.rag.applicability import resolve_legal_as_of
from app.services.audit.jobs import create_single_audit_job
from app.schemas.contract import RiskStatusUpdate, SignDateConfirmation


@pytest.fixture
def data(tmp_path):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(username='legal', password_hash='x', role='legal', department='法务部')
        db.add(user)
        db.flush()
        path = tmp_path / '合同.txt'
        path.write_bytes(encrypt_bytes(('采购合同\n甲方：甲公司\n乙方：乙公司\n签订日期：2026年10月01日\n' + '付款期限为三十日。' * 40).encode('utf-8')))
        contract = Contract(filename='合同.txt', storage_path=str(path), department='法务部', uploaded_by=user.id,
                            status='parsed', content_sha256='same-file', elements_json=json.dumps({'sign_date': '2026年10月01日'}))
        db.add(contract)
        db.commit()
        app = FastAPI()
        app.include_router(contracts.router, prefix='/contracts')
        app.include_router(risks_endpoint.router, prefix='/risks')
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: user
        with TestClient(app) as client:
            yield db, user, contract, client
    engine.dispose()


def confirm(data, value='2026-10-02'):
    _, _, contract, client = data
    return client.patch(f'/contracts/{contract.id}/sign-date', json={'sign_date': value})


def test_confirm_persists_actor_and_does_not_upgrade_evidence(data):
    db, user, contract, client = data
    risk = Risk(contract_id=contract.id, category='付款', level='high', basis='待核验', suggestion='待复核', original_text='原文',
                evidence_status='supported', support_relation_status='supported', decision_trace_json='{"evidence_validation":{"mode":"manual_only"}}')
    db.add(risk)
    db.commit()
    response = confirm(data)
    assert response.status_code == 200
    payload = response.json()
    assert payload['sign_date'] == '2026-10-02'
    assert payload['contract_type'] == contract.contract_type
    assert payload['confirmed'] is True
    assert payload['confirmed_by'] == user.id
    assert payload['confirmed_at']
    assert payload['audit_invalidated'] is True
    db.expire_all()
    assert client.get(f'/contracts/{contract.id}/sign-date').json() == payload
    saved = json.loads(contract.elements_json)
    assert saved['sign_date_confirmed'] is True
    assert saved['sign_date_content_sha256'] == contract.content_sha256
    assert resolve_legal_as_of(saved).as_of.isoformat() == '2026-10-02'
    assert db.query(AuditLog).filter_by(action='confirm_sign_date').count() == 1
    assert risk.decision_trace_json == '{"evidence_validation":{"mode":"manual_only"}}'
    assert evidence_validation_mode(risk.decision_trace_json) == 'manual_only'


@pytest.mark.parametrize('value', ['', '2026-02-30', '2026年10月02日', '2026-10-02T00:00:00Z', 1790899200, None])
def test_invalid_date_is_rejected(data, value):
    assert confirm(data, value).status_code == 422


def test_date_permission_and_department_boundaries(data):
    db, user, contract, client = data
    user.role = 'business'
    db.commit()
    assert confirm(data).status_code == 403
    user.role = 'legal'
    user.department = '其他部门'
    db.commit()
    assert confirm(data).status_code == 403
    assert client.get(f'/contracts/{contract.id}/sign-date').status_code == 403


@pytest.mark.parametrize('state', ['queued', 'parsing', 'reviewing', 'validating', 'auditing'])
def test_active_contract_cannot_change_date(data, state):
    db, _, contract, _ = data
    contract.status = state
    db.commit()
    assert confirm(data).status_code == 409


def test_active_job_blocks_date_even_if_contract_status_is_parsed(data):
    db, user, contract, _ = data
    batch = AuditBatch(owner_id=user.id, department=user.department, idempotency_key='date-test-key', status='running')
    db.add(batch)
    db.flush()
    db.add(AuditBatchItem(batch_id=batch.id, contract_id=contract.id, filename=contract.filename, status='queued', audit_generation=1))
    db.commit()
    assert confirm(data).status_code == 409


def test_legacy_completed_audit_without_job_is_invalidated(data):
    db, _, contract, _ = data
    contract.status = 'done'
    db.add(Risk(contract_id=contract.id, category='历史风险', level='high', original_text='历史条款', basis='历史证据', suggestion='待复核'))
    db.commit()
    assert confirm(data).json()['audit_invalidated'] is True
    db.refresh(contract)
    assert contract.audit_generation == 1


def test_unparsed_upload_cannot_be_confirmed(data):
    db, _, contract, _ = data
    contract.status = 'uploaded'
    db.commit()
    assert confirm(data).status_code == 409


@pytest.mark.parametrize('has_job', [False, True])
def test_date_change_rejects_old_risk_review_without_erasing_history(data, has_job):
    db, user, contract, client = data
    contract.status = 'done'
    job_id = None
    if has_job:
        contract.audit_generation = 1
        batch = AuditBatch(owner_id=user.id, department=user.department, idempotency_key='stale-risk', status='done')
        db.add(batch)
        db.flush()
        item = AuditBatchItem(batch_id=batch.id, contract_id=contract.id, filename=contract.filename, status='done', audit_generation=1)
        db.add(item)
        db.flush()
        job_id = item.id
    risk = Risk(contract_id=contract.id, audit_job_id=job_id, category='历史风险', level='high', original_text='原文', basis='证据', suggestion='待复核', review_status='pending')
    db.add(risk)
    db.commit()
    assert confirm(data).status_code == 200
    response = client.patch(f'/risks/{risk.id}/status', json={'review_status': 'confirmed', 'review_comment': '尝试复核旧代次'})
    assert response.status_code == 409
    db.refresh(risk)
    assert risk.review_status == 'pending'
    assert risk.basis == '证据'


def test_parsed_contract_without_history_does_not_invalidate(data):
    assert confirm(data).json()['audit_invalidated'] is False


def test_first_confirmation_after_audit_invalidates_but_keeps_history(data):
    db, user, contract, client = data
    contract.audit_generation = 1
    contract.status = 'done'
    batch = AuditBatch(owner_id=user.id, department=user.department, idempotency_key='completed-key', status='done')
    db.add(batch)
    db.flush()
    item = AuditBatchItem(batch_id=batch.id, contract_id=contract.id, filename=contract.filename, status='done', audit_generation=1, result_json='{"status":"done","risk_count":0}')
    db.add(item)
    db.flush()
    workflow = AuditWorkflow(contract_id=contract.id, audit_generation=1, audit_job_id=item.id, snapshot_json='{}', published_fingerprint='published')
    db.add(workflow)
    risk = Risk(contract_id=contract.id, audit_job_id=item.id, category='原风险', level='high', original_text='原条款', basis='原证据', suggestion='待复核', review_status='confirmed')
    db.add(risk)
    db.commit()
    response = confirm(data)
    assert response.status_code == 200
    assert response.json()['audit_invalidated'] is True
    db.refresh(contract)
    assert contract.audit_generation == 2
    assert contract.status == 'parsed'
    assert db.get(AuditWorkflow, workflow.id).published_fingerprint == 'published'
    assert db.get(AuditBatchItem, item.id).result_json == '{"status":"done","risk_count":0}'
    assert db.get(Risk, risk.id).basis == '原证据'
    assert db.get(Risk, risk.id).review_status == 'confirmed'
    assert workflow_view(db, contract.id, user)['can_finalize'] is False
    status = client.get(f'/contracts/{contract.id}/audit-status?job_id={item.id}').json()
    assert status['result_stale'] is True
    assert status['requires_review'] is True
    assert '签订日期' in status['review_reason']
    previous_generation = contract.audit_generation
    assert confirm(data).status_code == 200
    db.refresh(contract)
    assert contract.audit_generation == previous_generation


def test_reparse_keeps_manual_date_for_same_content_only(data, monkeypatch):
    db, _, contract, client = data
    assert confirm(data).status_code == 200
    monkeypatch.setattr(contracts, 'save_parse_cache', lambda *a: None)
    response = client.post(f'/contracts/{contract.id}/parse')
    assert response.status_code == 200
    assert response.json()['elements']['sign_date'] == '2026-10-02'
    assert response.json()['elements']['sign_date_confirmed'] is True
    contract.content_sha256 = 'different-file'
    db.commit()
    response = client.post(f'/contracts/{contract.id}/parse')
    assert response.status_code == 200
    assert response.json()['elements'].get('sign_date_confirmed') is not True


def test_auto_parsed_date_never_counts_as_confirmed(data):
    _, _, contract, client = data
    response = client.get(f'/contracts/{contract.id}/sign-date')
    assert response.status_code == 200
    assert response.json()['confirmed'] is False
    assert response.json()['sign_date'] == '2026年10月01日'


@pytest.mark.parametrize('state', ['queued', 'parsing', 'auditing'])
def test_active_import_blocks_confirmation(data, state):
    db, user, contract, _ = data
    batch = ImportBatch(owner_id=user.id, idempotency_key='active-import')
    batch.items.append(ImportBatchItem(contract_id=contract.id, filename=contract.filename, status=state))
    db.add(batch)
    db.commit()
    assert confirm(data).status_code == 409


@pytest.mark.parametrize('failure', [False, True])
def test_import_reparse_retains_same_file_confirmation_even_on_failure(data, monkeypatch, failure):
    from app.tasks import import_tasks
    db, user, contract, _ = data
    assert confirm(data).status_code == 200
    batch = ImportBatch(owner_id=user.id, idempotency_key='reparse-import')
    batch.items.append(ImportBatchItem(contract_id=contract.id, filename=contract.filename, status='queued'))
    db.add(batch)
    db.commit()
    item_id = batch.items[0].id
    monkeypatch.setattr(import_tasks, 'SessionLocal', lambda: Session(db.get_bind()))
    monkeypatch.setattr(import_tasks, 'save_parse_cache', lambda *args: None)
    if failure:
        def unavailable(*args):
            raise RuntimeError('解析服务暂不可用')
        monkeypatch.setattr(import_tasks, 'extract_document', unavailable)
    import_tasks.parse_import_item.run(item_id)
    db.expire_all()
    saved = json.loads(contract.elements_json)
    assert saved['sign_date'] == '2026-10-02'
    assert saved['sign_date_confirmed'] is True
    assert saved['sign_date_confirmed_by'] == user.id


@pytest.mark.parametrize('interleaving', ['confirm_date', 'start_audit'])
def test_concurrent_parse_cannot_overwrite_date_or_new_audit(tmp_path, monkeypatch, interleaving):
    """真实双连接交错：慢解析期间另一会话确认日期或领取审查。"""
    engine = create_engine(f'sqlite:///{(tmp_path / "concurrent.sqlite").as_posix()}')
    Base.metadata.create_all(engine)
    path = tmp_path / '并发合同.txt'
    path.write_bytes(encrypt_bytes(('采购合同\n签订日期：2026年10月01日\n' + '付款期限为三十日。' * 40).encode('utf-8')))
    with Session(engine) as setup:
        actor = User(username='concurrent-legal', password_hash='x', role='legal', department='法务部')
        setup.add(actor)
        setup.flush()
        row = Contract(filename=path.name, storage_path=str(path), department=actor.department,
                       uploaded_by=actor.id, status='review_required' if interleaving == 'start_audit' else 'parsed', content_sha256='same-file',
                       elements_json='{"sign_date":"2026年10月01日"}')
        setup.add(row)
        setup.commit()
        contract_id, actor_id = row.id, actor.id
    original_extract = contracts.extract_document
    concurrent_values = {}

    def extract_with_interleaving(storage_path):
        with Session(engine) as other:
            actor = other.get(User, actor_id)
            if interleaving == 'confirm_date':
                confirmed = contracts.confirm_sign_date(contract_id, SignDateConfirmation(sign_date='2026-10-02'), other, actor)
                assert confirmed['confirmed'] is True
            else:
                create_single_audit_job(other, contract=other.get(Contract, contract_id), user=actor,
                                        idempotency_key='concurrent-audit-key', contract_type='采购合同', dimensions=[])
            other.expire_all()
            latest = other.get(Contract, contract_id)
            concurrent_values.update(elements_json=latest.elements_json, status=latest.status,
                                     audit_generation=latest.audit_generation)
        return original_extract(storage_path)

    monkeypatch.setattr(contracts, 'extract_document', extract_with_interleaving)
    with Session(engine) as parsing:
        actor = parsing.get(User, actor_id)
        with pytest.raises(HTTPException) as conflict:
            contracts.parse_contract(contract_id, parsing, actor)
        assert conflict.value.status_code == 409
    with Session(engine) as check:
        latest = check.get(Contract, contract_id)
        assert latest.elements_json == concurrent_values['elements_json']
        assert latest.status == concurrent_values['status']
        assert latest.audit_generation == concurrent_values['audit_generation']
        assert check.query(AuditLog).filter_by(action='parse').count() == 0
        if interleaving == 'confirm_date':
            values = json.loads(latest.elements_json)
            assert values['sign_date'] == '2026-10-02'
            assert values['sign_date_confirmed'] is True
            assert values['sign_date_confirmed_by'] == actor_id
            assert values['sign_date_confirmed_by_name'] == 'concurrent-legal'
            assert values['sign_date_confirmed_at']
            assert values['sign_date_content_sha256'] == 'same-file'
        else:
            assert latest.status == 'reviewing'
            assert check.query(AuditBatchItem).filter_by(contract_id=contract_id).one().status == 'queued'
    engine.dispose()


@pytest.mark.parametrize(('old_has_job', 'new_has_job'), [(True, True), (False, True), (False, False)])
def test_date_confirmation_then_reaudit_keeps_old_pending_risk(data, monkeypatch, old_has_job, new_has_job):
    """日期重审保留旧代次未复核证据，包括历史无任务编号的记录。"""
    from app.services.audit import runner
    from app.services.audit.result_quality import AuditCoverage
    from app.services.parser.extractor import DocumentParseResult
    db, user, contract, client = data
    contract.status = 'done'
    contract.audit_generation = 1
    old_job_id = None
    if old_has_job:
        old_batch = AuditBatch(owner_id=user.id, department=user.department, idempotency_key='old-date-audit', status='done')
        db.add(old_batch)
        db.flush()
        old_job = AuditBatchItem(batch_id=old_batch.id, contract_id=contract.id, filename=contract.filename,
                                status='done', audit_generation=1, result_json='{"status":"done","risk_count":1}')
        db.add(old_job)
        db.flush()
        old_job_id = old_job.id
    old_risk = Risk(contract_id=contract.id, audit_job_id=old_job_id, category='历史待复核', level='high',
                    original_text='历史原文', basis='历史依据', suggestion='历史建议', review_status='pending',
                    source_clause_ids_json='["旧条款"]', contract_evidence_json='[{"chunk_id":"historical-chunk","clause_id":"旧条款","anchors":[{"page_number":1}]}]')
    db.add(old_risk)
    old_clause = ContractClause(contract_id=contract.id, audit_generation=1, chunk_id='historical-chunk',
                                clause_id='旧条款', content='历史原文', source_anchors_json='[{"page_number":1}]')
    db.add(old_clause)
    db.commit()
    risk_id = old_risk.id
    assert confirm(data).status_code == 200
    def computed(*args, **kwargs):
        return {'_parsed': DocumentParseResult(text='contract ' * 40, source='native'),
                '_risks': [], '_issues': [], '_coverage': AuditCoverage(1, 1)}
    monkeypatch.setattr(runner, '_compute_audit', computed)
    if new_has_job:
        created = create_single_audit_job(db, contract=contract, user=user,
                                         idempotency_key='new-date-audit', contract_type='采购合同', dimensions=[])
        created.item.execution_token = 'date-audit-token'
        db.commit()
        result = runner.run_audit(db, contract, generation=created.item.audit_generation,
                                  batch_item_id=created.item.id, execution_token='date-audit-token')
    else:
        result = runner.run_audit(db, contract)
    assert result['status'] == 'done'
    db.expire_all()
    saved = db.get(Risk, risk_id)
    assert saved is not None
    assert saved.review_status == 'pending'
    assert saved.original_text == '历史原文'
    assert saved.basis == '历史依据'
    historical_clause = db.query(ContractClause).filter_by(contract_id=contract.id, audit_generation=1, chunk_id='historical-chunk').first()
    assert historical_clause is not None
    assert historical_clause.content == '历史原文'
    assert json.loads(historical_clause.source_anchors_json) == [{'page_number': 1}]
    assert json.loads(saved.contract_evidence_json)[0]['chunk_id'] == historical_clause.chunk_id
    path = f'/contracts/{contract.id}/risks' + (f'?job_id={old_job_id}' if old_job_id else '')
    assert any(row['id'] == risk_id for row in client.get(path).json())


def test_concurrent_date_confirmation_prevents_stale_risk_review(tmp_path, monkeypatch):
    """SQLite 忽略行锁，代次检查之后发生的日期确认仍须由写入 CAS 拦截。"""
    engine = create_engine(f'sqlite:///{(tmp_path / "risk-concurrent.sqlite").as_posix()}')
    Base.metadata.create_all(engine)
    with Session(engine) as setup:
        actor = User(username='risk-concurrent', password_hash='x', role='legal', department='法务部')
        setup.add(actor)
        setup.flush()
        contract = Contract(filename='并发复核.txt', storage_path='unused', department=actor.department,
                            uploaded_by=actor.id, status='done', content_sha256='same-file', audit_generation=1)
        setup.add(contract)
        setup.flush()
        batch = AuditBatch(owner_id=actor.id, department=actor.department, idempotency_key='risk-concurrent-audit', status='done')
        setup.add(batch)
        setup.flush()
        job = AuditBatchItem(batch_id=batch.id, contract_id=contract.id, filename=contract.filename, status='done', audit_generation=1)
        setup.add(job)
        setup.flush()
        risk = Risk(contract_id=contract.id, audit_job_id=job.id, category='待复核', level='high', original_text='原文', basis='依据', suggestion='建议', review_status='pending')
        setup.add(risk)
        setup.commit()
        contract_id, actor_id, job_id, risk_id = contract.id, actor.id, job.id, risk.id
    with Session(engine) as reviewing:
        actor = reviewing.get(User, actor_id)
        original_get = reviewing.get
        interleaved = False
        def get_with_concurrent_confirmation(entity, identity, *args, **kwargs):
            nonlocal interleaved
            result = original_get(entity, identity, *args, **kwargs)
            if entity is AuditBatchItem and identity == job_id and not interleaved:
                interleaved = True
                with Session(engine) as other:
                    confirmation = contracts.confirm_sign_date(contract_id, SignDateConfirmation(sign_date='2026-10-02'), other, other.get(User, actor_id))
                    assert confirmation['confirmed'] is True
            return result
        monkeypatch.setattr(reviewing, 'get', get_with_concurrent_confirmation)
        with pytest.raises(HTTPException) as conflict:
            risks_endpoint.update_risk_status(risk_id, RiskStatusUpdate(review_status='confirmed', review_comment='旧代次复核意见'), reviewing, actor)
        assert conflict.value.status_code == 409
    with Session(engine) as check:
        assert check.get(Contract, contract_id).audit_generation == 2
        assert check.get(Risk, risk_id).review_status == 'pending'
        assert check.query(AuditLog).filter_by(action='update_risk').count() == 0
    engine.dispose()
