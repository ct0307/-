"""日期变更不能与旧终审交错提交，使用文件SQLite双连接验证。"""
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.models import AuditLog, AuditWorkflow, Contract, Risk, User
from app.api.v1.endpoints.contracts import confirm_sign_date
from app.schemas.contract import SignDateConfirmation
from app.services.audit import finalization


def test_date_changed_after_snapshot_prevents_old_finalization(tmp_path, monkeypatch):
    engine = create_engine(f'sqlite:///{(tmp_path / "race.db").as_posix()}')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(username='legal', password_hash='x', role='legal', department='采购')
        db.add(user); db.flush()
        contract = Contract(filename='测试.txt', storage_path='unused', department='采购',
                            uploaded_by=user.id, status='review_required', audit_generation=1,
                            content_sha256='a' * 64, elements_json=json.dumps({'sign_date': '2026-11-01'}))
        db.add(contract); db.flush()
        db.add(Risk(contract_id=contract.id, category='付款', level='high', agent='legal',
                    original_text='验收后付款', basis='未核验', suggestion='人工确认', review_status='confirmed'))
        finalization.save_workflow(db, contract, None, {'directed_reviews': []}, [])
        db.commit()
        view = finalization.workflow_view(db, contract.id, user)
        values = dict(expected_generation=1, expected_version=view['version'], review_fingerprint=view['review_fingerprint'],
                      comment='合成样本终审意见', quality_comment='已核对原件', conflict_resolutions={})
        contract_id, user_id = contract.id, user.id
        original_view = finalization._view
        interleaved = False

        def view_then_change_date(*args):
            nonlocal interleaved
            result = original_view(*args)
            if not interleaved:
                interleaved = True
                with Session(engine) as other:
                    confirm_sign_date(contract_id, SignDateConfirmation(sign_date='2026-11-02'), other, other.get(User, user_id))
            return result

        monkeypatch.setattr(finalization, '_view', view_then_change_date)
        with pytest.raises(HTTPException) as caught:
            finalization.finalize_workflow(db, contract.id, user, values)
        assert caught.value.status_code == 409
        db.rollback(); db.expire_all()
        assert db.get(Contract, contract_id).audit_generation == 2
        assert db.query(AuditWorkflow).one().published_fingerprint == ''
        assert db.query(AuditLog).filter_by(action='finalize_audit').count() == 0
    engine.dispose()
