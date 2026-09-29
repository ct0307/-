from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import rectifications
from app.schemas.contract import RectificationCreate, RectificationStatusUpdate


class _Query:
    def __init__(self, row):
        self.row = row

    def filter(self, *_args):
        return self

    def first(self):
        return self.row


class _Db:
    def __init__(self, row):
        self.row = row

    def query(self, *_args):
        return _Query(self.row)

    def commit(self):
        pass

    def refresh(self, *_args):
        pass


def _row(status: str = "处理中"):
    return SimpleNamespace(
        id=1,
        contract="采购合同.pdf",
        risk="验收标准不明",
        level="high",
        owner="legal",
        status=status,
        created="2026-09-17",
        due="2026-09-24",
        note="补充验收条款",
        risk_id=7,
        resolution="",
        review_comment="",
        submitted_at=None,
        closed_at=None,
    )


@pytest.fixture(autouse=True)
def _disable_audit_log(monkeypatch):
    monkeypatch.setattr(rectifications.audit_log, "record", lambda *_args, **_kwargs: None)
    # 本文件只验证流转；真实部门授权由 test_workflow_authorization 的 SQLite 集成测试覆盖。
    monkeypatch.setattr(rectifications, "load_authorized_risk", lambda *_args: (None, None))


def test_processing_item_requires_resolution_before_review():
    row = _row()
    with pytest.raises(HTTPException) as caught:
        rectifications.update_rectification_status(
            "RC001",
            RectificationStatusUpdate(status="待复核"),
            _Db(row),
            SimpleNamespace(id=2, role="legal"),
        )
    assert caught.value.status_code == 400
    assert row.status == "处理中"


def test_review_submission_and_approval_form_a_two_step_closure():
    row = _row()
    db = _Db(row)
    user = SimpleNamespace(id=2, role="legal")

    submitted = rectifications.update_rectification_status(
        "RC001",
        RectificationStatusUpdate(status="待复核", resolution="已补充验收标准并完成签章"),
        db,
        user,
    )
    assert submitted.status == "待复核"
    assert submitted.submitted_at is not None
    assert submitted.closed_at is None

    approved = rectifications.update_rectification_status(
        "RC001",
        RectificationStatusUpdate(status="已闭环", review_comment="材料齐全，验收通过"),
        db,
        user,
    )
    assert approved.status == "已闭环"
    assert approved.closed_at is not None


def test_review_rejection_requires_comment():
    row = _row("待复核")
    row.resolution = "已提交修订版"
    with pytest.raises(HTTPException) as caught:
        rectifications.update_rectification_status(
            "RC001",
            RectificationStatusUpdate(status="处理中"),
            _Db(row),
            SimpleNamespace(id=2, role="legal"),
        )
    assert caught.value.status_code == 400
    assert row.status == "待复核"


def test_cannot_skip_review_and_close_processing_item():
    row = _row()
    with pytest.raises(HTTPException) as caught:
        rectifications.update_rectification_status(
            "RC001",
            RectificationStatusUpdate(status="已闭环", resolution="已修改"),
            _Db(row),
            SimpleNamespace(id=2, role="legal"),
        )
    assert caught.value.status_code == 409
    assert row.status == "处理中"


def test_new_item_cannot_start_as_closed():
    with pytest.raises(HTTPException) as caught:
        rectifications.create_rectification(
            RectificationCreate(
                contract="采购合同.pdf",
                risk="验收标准不明",
                status="已闭环",
            ),
            _Db(None),
            SimpleNamespace(id=2, role="legal"),
        )
    assert caught.value.status_code == 400


def test_approval_requires_review_comment():
    row = _row("待复核")
    row.resolution = "已补充验收标准"
    with pytest.raises(HTTPException) as caught:
        rectifications.update_rectification_status(
            "RC001",
            RectificationStatusUpdate(status="已闭环"),
            _Db(row),
            SimpleNamespace(id=2, role="legal"),
        )
    assert caught.value.status_code == 400
    assert row.status == "待复核"
