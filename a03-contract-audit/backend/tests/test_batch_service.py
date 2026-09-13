"""持久化批次状态汇总契约。"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.models import AuditBatch
from app.services.batch.service import (
    InvalidBatchTransition,
    retry_failed_item,
    summarize,
    transition_item,
)


def test_batch_progress_counts_terminal_items():
    progress = summarize(["done", "failed", "reviewing"])

    assert progress.total == 3
    assert progress.completed == 2
    assert progress.failed == 1
    assert progress.status == "running"


def test_batch_progress_reports_partial_failure_at_terminal_state():
    progress = summarize(["done", "failed", "done"])

    assert progress.completed == 3
    assert progress.status == "partial_failed"


def test_batch_progress_reports_review_required_without_failures():
    progress = summarize(["done", "review_required", "done"])

    assert progress.completed == 3
    assert progress.failed == 0
    assert progress.status == "review_required"


def test_batch_progress_reports_all_failed():
    progress = summarize(["failed", "failed"])

    assert progress.status == "failed"
    assert progress.failed == 2


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("queued", "parsing"),
        ("parsing", "reviewing"),
        ("reviewing", "validating"),
        ("validating", "done"),
        ("validating", "review_required"),
        ("validating", "failed"),
        ("failed", "queued"),
    ],
)
def test_item_transition_accepts_declared_state_machine(current, target):
    assert transition_item(current, target) == target


def test_item_transition_rejects_skipping_validation():
    with pytest.raises(InvalidBatchTransition):
        transition_item("reviewing", "done")


def test_review_required_is_terminal():
    with pytest.raises(InvalidBatchTransition):
        transition_item("review_required", "queued")


def test_failed_item_retry_is_idempotent():
    first = retry_failed_item("failed", attempts=1)
    second = retry_failed_item(first.status, attempts=first.attempts)

    assert first.status == "queued"
    assert first.attempts == 2
    assert second == first


def test_batch_idempotency_key_is_unique_per_owner():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(AuditBatch(owner_id=7, department="采购中心", idempotency_key="request-1"))
        db.commit()
        db.add(AuditBatch(owner_id=7, department="采购中心", idempotency_key="request-1"))
        with pytest.raises(IntegrityError):
            db.commit()
