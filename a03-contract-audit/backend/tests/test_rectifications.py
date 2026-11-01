"""整改流转回归使用真实 SQLite，所有验收遵守职责分离。"""
import pytest
from fastapi import HTTPException
from tests.test_rectification_closure import data,create,update,submit

def test_processing_item_requires_resolution_before_review(data):
    row=update(data,create(data),'处理中')
    with pytest.raises(HTTPException) as e: update(data,row,'待复核',evidence_contract_ids=[data[2][1].id],after_text='新条款')
    assert e.value.status_code==400

def test_review_submission_and_approval_form_a_two_step_closure(data):
    row=submit(data,update(data,create(data),'处理中'))
    assert row.submitted_at and row.closed_at is None
    row=update(data,row,'已闭环',user=1,review_comment='独立验收通过')
    assert row.closed_at

def test_review_rejection_requires_comment(data):
    row=submit(data,update(data,create(data),'处理中'))
    with pytest.raises(HTTPException) as e: update(data,row,'处理中',user=1)
    assert e.value.status_code==400

def test_cannot_skip_review_and_close_processing_item(data):
    row=update(data,create(data),'处理中')
    with pytest.raises(HTTPException) as e: update(data,row,'已闭环',resolution='完成')
    assert e.value.status_code==409

def test_new_item_cannot_start_as_closed(data):
    with pytest.raises(HTTPException) as e: create(data,status='已闭环')
    assert e.value.status_code==400

def test_approval_requires_review_comment(data):
    row=submit(data,update(data,create(data),'处理中'))
    with pytest.raises(HTTPException) as e: update(data,row,'已闭环',user=1)
    assert e.value.status_code==400
