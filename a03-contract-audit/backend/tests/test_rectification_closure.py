"""真实 SQLite 验证整改职责分离、证据、事件和并发。"""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.db.session import Base
from app.models.models import User, Contract, Risk, Rectification, RectificationEvent
from app.api.v1.endpoints import rectifications as api
from app.schemas.contract import RectificationCreate, RectificationStatusUpdate, RectificationPlanUpdate, RectificationEscalate

@pytest.fixture
def data():
    engine = create_engine('sqlite:///:memory:',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        users = [User(username=n,password_hash='x',role=r,department=d) for n,r,d in [('owner','business','采购'),('legal','legal','采购'),('admin','admin','管理'),('otheradmin','admin','管理'),('foreign','business','财务')]]
        db.add_all(users); db.flush()
        materials = [Contract(filename=n+'.txt',storage_path='unused',department=d,uploaded_by=users[0].id,content_sha256=h*64) for n,d,h in [('source','采购','a'),('evidence','采购','b'),('foreign','财务','c')]]
        db.add_all(materials); db.flush()
        risk=Risk(contract_id=materials[0].id,category='付款',level='high',original_text='原条款',original_text_verified=False,basis='待核验',suggestion='修改',review_status='confirmed')
        db.add(risk); db.commit()
        yield db,users,materials,risk
    engine.dispose()

def create(data,**extra):
    payload=dict(contract='伪造',risk='伪造',risk_id=data[3].id,owner='owner',due='2027-01-01',note='补充条款',acceptance_criteria='提供签章件',contract_stage='unsigned',handling_method='revision')
    payload.update(extra)
    return api.create_rectification(RectificationCreate(**payload),data[0],data[1][1])

def update(data,row,status,user=0,**fields):
    return api.update_rectification_status(row.id,RectificationStatusUpdate(status=status,version=row.version,**fields),data[0],data[1][user])

def submit(data,row,user=0):
    return update(data,row,'待复核',user=user,resolution='修订完成',evidence_contract_ids=[data[2][1].id],after_text='新条款')

def test_create_requires_plan(data):
    with pytest.raises(HTTPException) as e: create(data,acceptance_criteria='')
    assert e.value.status_code==422

@pytest.mark.parametrize('owner',['missing','foreign'])
def test_owner_must_be_registered_and_authorized(data,owner):
    with pytest.raises(HTTPException) as e: create(data,owner=owner)
    assert e.value.status_code==422

def test_no_evidence_cannot_submit(data):
    row=update(data,create(data),'处理中')
    with pytest.raises(HTTPException) as e: update(data,row,'待复核',resolution='完成',after_text='新条款')
    assert e.value.status_code==400

def test_self_review_blocked_and_separate_review_closes(data):
    row=submit(data,update(data,create(data,owner='legal'),'处理中',user=1),user=1)
    with pytest.raises(HTTPException) as e: update(data,row,'已闭环',user=1,review_comment='本人验收')
    assert e.value.status_code==403
    row=update(data,row,'已闭环',user=2,review_comment='独立验收通过')
    assert row.closed_at and row.status=='已闭环'
    assert row.evidence[0].content_sha256=='b'*64
    assert [e.action for e in row.events]==['create','start','submit','approve']

def test_stale_version_returns_conflict(data):
    row=create(data); update(data,row,'处理中')
    with pytest.raises(HTTPException) as e: update(data,row,'处理中')
    assert e.value.status_code==409

def test_risk_acceptance_is_not_closure(data):
    row=update(data,create(data,owner='admin'),'处理中',user=2)
    row=update(data,row,'待风险接受',user=2,resolution='加强监控',acceptance_reason='客观限制',residual_risk='仍有付款争议')
    with pytest.raises(HTTPException) as e: update(data,row,'已接受风险',user=2,review_comment='自行批准')
    assert e.value.status_code==403
    row=update(data,row,'已接受风险',user=3,review_comment='批准保留风险')
    assert row.closed_at is None and row.accepted_at is not None
    assert row.residual_risk=='仍有付款争议'

@pytest.mark.parametrize('index',[0,2])
def test_original_or_foreign_evidence_rejected(data,index):
    row=update(data,create(data),'处理中')
    with pytest.raises(HTTPException) as e: update(data,row,'待复核',resolution='完成',after_text='新',evidence_contract_ids=[data[2][index].id])
    assert e.value.status_code in (400,403)

@pytest.mark.parametrize('stage,method',[('unknown','revision'),('signed','revision'),('unsigned','supplement')])
def test_stage_constraints(data,stage,method):
    if stage!='unknown':
        with pytest.raises(HTTPException) as e: create(data,contract_stage=stage,handling_method=method)
        assert e.value.status_code==422
    else:
        row=update(data,create(data,contract_stage=stage,handling_method=method),'处理中')
        with pytest.raises(HTTPException) as e: submit(data,row)
        assert e.value.status_code==400

def test_rejection_resubmission_preserves_events_and_requires_fresh_comment(data):
    row=submit(data,update(data,create(data),'处理中'))
    row=update(data,row,'处理中',user=1,review_comment='缺少签章')
    row=submit(data,row)
    with pytest.raises(HTTPException) as e: update(data,row,'已闭环',user=1)
    assert e.value.status_code==400
    row=update(data,row,'已闭环',user=1,review_comment='补正通过')
    assert row.events[3].snapshot['review_comment']=='缺少签章'
    assert row.events[-1].snapshot['review_comment']=='补正通过'

def test_plan_reassignment_is_audited_and_new_owner_executes(data):
    row=create(data)
    row=api.update_rectification_plan(row.id,RectificationPlanUpdate(version=row.version,owner='legal'),data[0],data[1][1])
    assert row.events[-1].snapshot['previous_plan']['owner']=='owner'
    assert row.events[-1].snapshot['owner']=='legal'
    with pytest.raises(HTTPException) as e: update(data,row,'处理中')
    assert e.value.status_code==403
    assert update(data,row,'处理中',user=1).status=='处理中'

def test_escalation_requires_new_reason_and_preserves_history(data):
    row=create(data)
    row=api.escalate_rectification(row.id,RectificationEscalate(version=row.version,reason='高风险需协调'),data[0],data[1][0])
    assert row.escalated_by==data[1][0].id
    assert row.events[-1].action=='escalate'
    assert row.events[-1].snapshot['escalation_reason']=='高风险需协调'
    with pytest.raises(HTTPException) as e: api.escalate_rectification(row.id,RectificationEscalate(version=row.version,reason='  '),data[0],data[1][0])
    assert e.value.status_code==422

def test_deleted_evidence_rejected(data):
    from datetime import datetime, timezone
    data[2][1].deleted_at=datetime.now(timezone.utc);data[0].commit()
    row=update(data,create(data),'处理中')
    with pytest.raises(HTTPException) as e: submit(data,row)
    assert e.value.status_code==400

def test_review_cannot_rewrite_submission(data):
    row=submit(data,update(data,create(data),'处理中'))
    with pytest.raises(HTTPException) as e: update(data,row,'已闭环',user=1,review_comment='通过',resolution='篡改')
    assert e.value.status_code==400
    assert data[0].get(Rectification,1).resolution=='修订完成'

def test_finance_or_legal_cannot_approve_risk_acceptance(data):
    row=update(data,create(data),'处理中')
    row=update(data,row,'待风险接受',resolution='增加控制',acceptance_reason='客观限制',residual_risk='剩余风险')
    with pytest.raises(HTTPException) as e: update(data,row,'已接受风险',user=1,review_comment='通过')
    assert e.value.status_code==403

def test_business_cannot_manage_plan_or_review(data):
    row=create(data)
    with pytest.raises(HTTPException) as e: api.update_rectification_plan(row.id,RectificationPlanUpdate(version=row.version,note='篡改'),data[0],data[1][0])
    assert e.value.status_code==403
    row=submit(data,update(data,row,'处理中'))
    with pytest.raises(HTTPException) as e: update(data,row,'已闭环',review_comment='通过')
    assert e.value.status_code==403

def test_participants_materials_and_capabilities_respect_source_department(data):
    people=api.list_participants(data[3].id,data[0],data[1][1])
    assert 'foreign' not in [p['username'] for p in people]
    assert [m['id'] for m in api.list_materials(data[3].id,data[0],data[1][2])]==[data[2][1].id]
    row=create(data)
    assert row.can_manage and not row.can_execute
    owned=api.list_rectifications(data[0],data[1][0])[0]
    assert owned.can_execute and not owned.can_review
    assert owned.department=='采购' and owned.original_text_verified is False

def test_admin_cannot_attach_other_department_evidence(data):
    row=update(data,create(data,owner='admin'),'处理中',user=2)
    with pytest.raises(HTTPException) as e: update(data,row,'待复核',user=2,resolution='完成',after_text='新',evidence_contract_ids=[data[2][2].id])
    assert e.value.status_code==403

def test_sqlalchemy_concurrency_rolls_back_event_and_returns_409(data):
    row=create(data)
    db=data[0]
    # 两个Session先读同一版本，第二次提交由数据库版本条件捕获竞争。
    with Session(db.bind) as other:
        stale=other.get(Rectification,1)
        update(data,row,'处理中')
        from app.services.rectification_workflow import persist
        stale.note='过期写入'
        with pytest.raises(HTTPException) as e: persist(other,stale,data[1][1],'update_plan','待处理')
        assert e.value.status_code==409
    assert db.query(RectificationEvent).count()==2

def test_legacy_rows_do_not_invent_evidence_or_acceptance(data):
    db=data[0]
    db.add(Rectification(contract='旧合同',risk='旧风险',risk_id=data[3].id,level='high',owner='',created='2026-10-01',due='2027-01-01'))
    db.commit()
    row=api.list_rectifications(db,data[1][1])[0]
    assert row.acceptance_criteria=='' and row.evidence==[] and row.events==[]
    assert row.contract_stage=='unknown' and row.submitted_by is None

def test_historical_pending_review_cannot_be_closed_without_verified_plan(data):
    db=data[0]
    db.add(Rectification(contract='旧合同',risk='旧风险',risk_id=data[3].id,level='high',owner='',status='待复核',created='2026-10-01',due='2027-01-01',resolution='旧结果'))
    db.commit()
    row=api.list_rectifications(db,data[1][1])[0]
    with pytest.raises(HTTPException) as e: update(data,row,'已闭环',user=1,review_comment='不能伪造验收')
    assert e.value.status_code in (400,422)

def test_unknown_stage_cannot_request_risk_acceptance(data):
    row=update(data,create(data,contract_stage='unknown'),'处理中')
    with pytest.raises(HTTPException) as e: update(data,row,'待风险接受',resolution='加强监控',acceptance_reason='约束',residual_risk='风险')
    assert e.value.status_code==400

def test_sqlite_incremental_columns_preserve_existing_rows(monkeypatch):
    from sqlalchemy import text, inspect
    from app.db import init_db
    engine=create_engine('sqlite:///:memory:')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE rectifications (id INTEGER PRIMARY KEY, contract VARCHAR(255), risk VARCHAR(255), level VARCHAR(8), owner VARCHAR(64), status VARCHAR(16), created VARCHAR(16), due VARCHAR(16), note TEXT, risk_id INTEGER, created_at DATETIME)'))
        conn.execute(text("INSERT INTO rectifications (id, contract, status) VALUES (1, '历史合同', '待处理')"))
    monkeypatch.setattr(init_db,'engine',engine)
    init_db._migrate_dev_columns()
    init_db._migrate_dev_columns()
    with engine.connect() as conn:
        old=conn.execute(text('SELECT contract, acceptance_criteria, contract_stage, evidence_json, submitted_by, version FROM rectifications')).one()
    assert tuple(old)==('历史合同','','unknown','[]',None,1)
    assert 'reviewed_at' in {c['name'] for c in inspect(engine).get_columns('rectifications')}
    engine.dispose()

def test_http_contract_static_routes_version_and_serialized_events(data):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.deps import get_current_user
    from app.db.session import get_db
    app=FastAPI()
    app.include_router(api.router,prefix='/rectifications')
    app.dependency_overrides[get_db]=lambda:data[0]
    app.dependency_overrides[get_current_user]=lambda:data[1][1]
    with TestClient(app) as client:
        assert client.get('/rectifications/participants',params={'risk_id':data[3].id}).status_code==200
        assert client.get('/rectifications/materials',params={'risk_id':data[3].id}).json()[0]['id']==data[2][1].id
        response=client.post('/rectifications',json=dict(risk_id=data[3].id,owner='legal',due='2027-01-01',note='修改',acceptance_criteria='核对签章',contract_stage='unsigned',handling_method='revision'))
        assert response.status_code==200
        body=response.json()
        assert body['events'][0]['action']=='create'
        assert body['events'][0]['snapshot']['before_text']=='原条款'
        assert body['original_text_verified'] is False
        assert client.patch('/rectifications/'+body['id'],json={'status':'处理中'}).status_code==422
        started=client.patch('/rectifications/'+body['id'],json={'status':'处理中','version':body['version']})
        assert started.status_code==200
        assert client.patch('/rectifications/'+body['id'],json={'status':'处理中','version':body['version']}).status_code==409

def test_reopen_keeps_previous_evidence_and_acceptance_in_events(data):
    row=submit(data,update(data,create(data),'处理中'))
    row=update(data,row,'已闭环',user=1,review_comment='验收通过')
    row=update(data,row,'待处理',user=1)
    assert row.closed_at is None
    assert row.events[-1].action=='reopen'
    assert row.events[-2].snapshot['closed_at'] is not None
    assert row.events[-2].snapshot['evidence'][0]['filename']=='evidence.txt'

@pytest.mark.parametrize('change',['deleted','hash','department','missing_hash'])
def test_approval_rechecks_material_snapshot_and_keeps_pending_state(data,change):
    from datetime import datetime, timezone
    row=submit(data,update(data,create(data),'处理中'))
    material=data[2][1]
    if change=='deleted': material.deleted_at=datetime.now(timezone.utc)
    elif change=='hash': material.content_sha256='c'*64
    elif change=='department': material.department='财务'
    else: material.content_sha256=None
    data[0].commit()
    with pytest.raises(HTTPException) as e: update(data,row,'已闭环',user=1,review_comment='不能接受失效材料')
    assert e.value.status_code in (400,403,409)
    assert data[0].get(Rectification,1).status=='待复核'
    assert data[0].query(RectificationEvent).count()==3

def test_persist_unexpected_failure_rolls_back_state_and_event(data,monkeypatch):
    from app.services import rectification_workflow
    row=create(data)
    def fail(*args,**kwargs): raise RuntimeError('模拟持久化失败')
    monkeypatch.setattr(rectification_workflow.audit_log,'record',fail)
    with pytest.raises(RuntimeError): update(data,row,'处理中')
    assert data[0].get(Rectification,1).status=='待处理'
    assert data[0].query(RectificationEvent).count()==1

def test_reopen_capability_only_for_professional_with_real_source(data):
    row=submit(data,update(data,create(data),'处理中'))
    row=update(data,row,'已闭环',user=1,review_comment='完成')
    assert row.can_reopen and not row.can_manage
    assert not api.list_rectifications(data[0],data[1][0])[0].can_reopen

def test_submission_requires_real_hash_instead_of_invented_legacy_hash(data):
    data[2][1].content_sha256=None;data[0].commit()
    row=update(data,create(data),'处理中')
    with pytest.raises(HTTPException) as e: submit(data,row)
    assert e.value.status_code==400
    assert data[0].get(Contract,data[2][1].id).content_sha256 is None

@pytest.mark.parametrize('due',['20270101','2027-W01-1'])
def test_due_date_is_strict_iso_calendar_date(data,due):
    with pytest.raises(HTTPException) as e: create(data,due=due)
    assert e.value.status_code==422

def test_review_rejects_other_department_before_mutation(data):
    row=submit(data,update(data,create(data),'处理中'))
    data[1][4].role='legal';data[0].commit()
    with pytest.raises(HTTPException) as e: update(data,row,'已闭环',user=4,review_comment='越权通过')
    assert e.value.status_code==403
    assert data[0].get(Rectification,1).status=='待复核'


@pytest.mark.parametrize('role', ['business', 'legal', 'finance', 'admin'])
def test_rectification_response_respects_role_masking_without_changing_evidence(data, role):
    """列表与事件快照遵守风险接口的原文权限，留存证据不受响应脱敏影响。"""
    import json
    from app.services.masking import mask_original_text

    db, users, _, risk = data
    original = '联系人：测试人员，电话13800138000；' + '合同条款' * 40 + '私密尾文'
    risk.original_text = original
    db.commit()
    row = create(data, note='请联系13800138000补齐材料')
    user = users[0]
    user.role = role
    db.commit()

    response = api.list_rectifications(db, user)[0]
    if role == 'business':
        assert response.before_text == mask_original_text(original)
        assert response.events[0].snapshot['before_text'] == mask_original_text(original)
        assert '13800138000' not in response.model_dump_json()
        assert '私密尾文' not in response.model_dump_json()
        assert response.can_execute is True
    else:
        assert response.before_text == original
        assert response.events[0].snapshot['before_text'] == original
        assert response.note == row.note
    assert db.get(Risk, risk.id).original_text == original
    saved = json.loads(db.query(RectificationEvent).one().snapshot_json)
    assert saved['before_text'] == original
    assert saved['note'] == '请联系13800138000补齐材料'


def test_business_submission_masks_nested_material_and_snapshot_fields(data):
    """写接口同样经统一响应脱敏，不能从重复序列化的证据字段取回敏感值。"""
    import json

    row = update(data, create(data), '处理中')
    response = update(data, row, '待复核', resolution='请联系13800138000核对',
        evidence_contract_ids=[data[2][1].id], after_text='联系人：测试人员，修改后条款')
    assert '13800138000' not in response.model_dump_json()
    assert '测试人员' not in response.model_dump_json()
    assert response.evidence[0].content_sha256 == 'b' * 64
    saved = data[0].get(Rectification, 1)
    assert saved.resolution == '请联系13800138000核对'
    assert saved.after_text == '联系人：测试人员，修改后条款'
    submitted = data[0].query(RectificationEvent).filter_by(action='submit').one()
    snapshot = json.loads(submitted.snapshot_json)
    assert json.loads(snapshot['evidence_json'])[0]['description'] == saved.resolution
    assert snapshot['evidence'][0]['description'] == saved.resolution


@pytest.mark.parametrize('username', ['owner@example.com', '13800138000'])
@pytest.mark.parametrize('is_owner', [True, False])
def test_business_owner_identity_preserves_own_execution_entry_only(data, username, is_owner):
    """仅本人登录标识可保留，其他业务查看者及历史快照仍执行脱敏。"""
    db, users, _, _ = data
    users[0].username = username
    users[4].department = users[0].department
    db.commit()
    row = create(data, owner=username)
    viewer = users[0] if is_owner else users[4]

    response = api.list_rectifications(db, viewer)[0]
    assert response.can_execute is is_owner
    assert response.owner == (username if is_owner else '[已脱敏]')
    assert response.events[0].snapshot['owner'] == '[已脱敏]'
    if is_owner:
        started = update(data, row, '处理中')
        assert started.owner == username
        assert started.can_execute is True
        assert all(event.snapshot['owner'] == '[已脱敏]' for event in started.events)
    else:
        assert username not in response.model_dump_json()
    assert db.get(Rectification, 1).owner == username
