"""终审必须绑定当前代次和完整人工决定，不篡改机器结论。"""
import json
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.db.session import Base
from app.models.models import Contract, Risk, User
from app.services.audit.finalization import save_workflow, workflow_view, finalize_workflow


@pytest.fixture
def data():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(username='legal',password_hash='x',role='legal',department='采购')
        db.add(user); db.flush()
        contract = Contract(filename='测试.txt',storage_path='unused',department='采购',uploaded_by=user.id,
                            status='review_required',audit_generation=1,requires_review=True)
        db.add(contract); db.flush()
        risk = Risk(contract_id=contract.id,category='付款',level='high',agent='legal',
                    original_text='验收后付款',basis='未核验',suggestion='人工确认',review_status='pending')
        db.add(risk); db.flush()
        save_workflow(db, contract, None, {'directed_reviews':[{'check_id':'X1','status':'manual_required'}]},
                      [{'id':'X1','verdict':'conflict'}])
        db.commit()
        yield db,user,contract,risk
    engine.dispose()


def payload(view):
    return dict(expected_generation=1, expected_version=view['version'], review_fingerprint=view['review_fingerprint'],
                comment='已完成终审，依据不足部分采用人工核验结论', quality_comment='已逐页核对原件并确认解析内容',
                conflict_resolutions={'X1':'已核对授权收款证明，保留人工判断'})


def test_pending_risks_block_finalization(data):
    db,user,contract,risk = data
    with pytest.raises(HTTPException) as error:
        finalize_workflow(db, contract.id, user, payload(workflow_view(db,contract.id,user)))
    assert error.value.status_code == 409


def test_publish_keeps_machine_flags_and_changed_review_invalidates(data):
    db,user,contract,risk = data
    risk.review_status='confirmed'; db.commit()
    view = workflow_view(db,contract.id,user)
    result = finalize_workflow(db,contract.id,user,payload(view))
    assert result['state'] == 'published'
    assert contract.requires_review is True
    assert risk.evidence_status != 'supported'
    risk.review_status='ignored'; db.commit()
    assert workflow_view(db,contract.id,user)['state'] == 'review_changed'


def test_stale_view_and_missing_conflict_decision_are_rejected(data):
    db,user,contract,risk = data
    risk.review_status='confirmed'; db.commit()
    view = workflow_view(db,contract.id,user)
    values=payload(view); values['conflict_resolutions']={}
    with pytest.raises(HTTPException): finalize_workflow(db,contract.id,user,values)
    contract.audit_generation=2; db.commit()
    with pytest.raises(HTTPException): finalize_workflow(db,contract.id,user,payload(view))


def test_foreign_department_and_business_cannot_finalize(data):
    db,user,contract,risk = data
    user.department='销售'; db.commit()
    with pytest.raises(HTTPException) as error: workflow_view(db,contract.id,user)
    assert error.value.status_code == 403
    user.department='采购'; user.role='business'; db.commit()
    with pytest.raises(HTTPException) as error: finalize_workflow(db,contract.id,user,{})
    assert error.value.status_code == 403


def test_same_status_new_human_comment_invalidates_publication(data):
    from app.api.v1.endpoints.risks import update_risk_status
    from app.schemas.contract import RiskStatusUpdate
    db, user, contract, risk = data
    update_risk_status(risk.id, RiskStatusUpdate(review_status='confirmed', review_comment='首次核验意见'), db, user)
    view = workflow_view(db, contract.id, user)
    assert finalize_workflow(db, contract.id, user, payload(view))['state'] == 'published'
    update_risk_status(risk.id, RiskStatusUpdate(review_status='confirmed', review_comment='补充了新的核验依据'), db, user)
    assert workflow_view(db, contract.id, user)['state'] == 'review_changed'


def test_stale_reviewer_cannot_overwrite_completed_finalization(data):
    db, user, contract, risk = data
    risk.review_status = 'confirmed'
    db.commit()
    old_values = payload(workflow_view(db, contract.id, user))
    finalize_workflow(db, contract.id, user, old_values)
    with pytest.raises(HTTPException) as caught:
        finalize_workflow(db, contract.id, user, old_values)
    assert caught.value.status_code == 409
    assert workflow_view(db, contract.id, user)['state'] == 'published'


def test_quality_ack_and_rectification_are_required_before_publication(data):
    db, user, contract, risk = data
    risk.review_status = 'confirmed'
    db.commit()
    values = payload(workflow_view(db, contract.id, user))
    values['quality_comment'] = ''
    with pytest.raises(HTTPException) as caught:
        finalize_workflow(db, contract.id, user, values)
    assert caught.value.status_code == 422
    risk.review_status = 'to_modify'
    db.commit()
    with pytest.raises(HTTPException) as caught:
        finalize_workflow(db, contract.id, user, payload(workflow_view(db, contract.id, user)))
    assert caught.value.status_code == 409


def test_missing_rectification_is_visible_before_publish_and_clears_when_created(data):
    from app.models.models import Rectification
    db, user, contract, risk = data
    risk.review_status = 'to_modify'
    db.commit()
    view = workflow_view(db, contract.id, user)
    assert view['missing_rectifications'] == [{'risk_id': risk.id, 'category': '付款'}]
    with pytest.raises(HTTPException) as caught:
        finalize_workflow(db, contract.id, user, payload(view))
    assert caught.value.status_code == 409
    assert '整改任务' in caught.value.detail
    db.add(Rectification(contract=contract.filename, risk='付款', level='high',
                         risk_id=risk.id, created='2026-11-03', due='2026-11-10'))
    db.commit()
    current = workflow_view(db, contract.id, user)
    assert current['missing_rectifications'] == []
    assert current['review_fingerprint'] != view['review_fingerprint']
    assert finalize_workflow(db, contract.id, user, payload(current))['state'] == 'published'
