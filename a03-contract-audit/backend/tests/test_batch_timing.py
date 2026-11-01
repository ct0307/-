"""批次耗时来自任务时间戳，未知和失败不伪装成零耗时。"""

from datetime import datetime, timedelta, timezone

import pytest

from app.schemas.batch import BatchItemOut


CREATED = datetime(2026, 11, 1, 1, 0, tzinfo=timezone.utc)


def item(**changes):
    return BatchItemOut.model_validate({
        "id": 1, "contract_id": 2, "filename": "synthetic.txt",
        "status": "done", "attempts": 0,
        "created_at": CREATED,
        "started_at": CREATED + timedelta(seconds=10),
        "finished_at": CREATED + timedelta(seconds=40),
        **changes,
    }).model_dump(mode="json")


@pytest.mark.parametrize("status", ["done", "review_required", "failed"])
def test_terminal_timing_includes_failed_tasks(status):
    result = item(status=status)
    assert result.get("queue_wait_ms") == 10000
    assert result.get("processing_ms") == 30000
    assert result.get("total_ms") == 40000


def test_missing_historical_timestamps_remain_unknown():
    result = item(created_at=None, started_at=None, finished_at=None)
    assert "total_ms" in result, "应显式提供未知耗时而非省略统计口径"
    assert result["queue_wait_ms"] is None
    assert result["processing_ms"] is None
    assert result["total_ms"] is None


def test_terminal_missing_finish_is_not_timed_until_now():
    result = item(finished_at=None)
    assert result.get("queue_wait_ms") == 10000
    assert result.get("processing_ms") is None
    assert result.get("total_ms") is None


def test_failure_before_start_has_no_processing_duration():
    result = item(status="failed", started_at=None)
    assert result.get("total_ms") == 40000
    assert result.get("processing_ms") is None
    assert result.get("queue_wait_ms") is None


def test_sqlite_naive_dates_and_utc_aware_dates_are_compatible():
    result = item(created_at=CREATED.replace(tzinfo=None))
    assert result.get("total_ms") == 40000


def test_invalid_timestamp_order_remains_unknown():
    result = item(started_at=CREATED - timedelta(seconds=1))
    assert result.get("queue_wait_ms") is None
    assert result.get("processing_ms") is None
    assert result.get("total_ms") is None


def test_unknown_start_still_has_terminal_end_to_end_duration():
    result = item(started_at=None)
    assert result.get("total_ms") == 40000
    assert result.get("processing_ms") is None


def test_nonterminal_elapsed_timing_has_explicit_clock():
    from app.services.batch.timing import item_timings

    result = item_timings(
        created_at=CREATED, started_at=None, finished_at=None,
        status="queued", now=CREATED + timedelta(seconds=12),
    )
    assert result == {"queue_wait_ms": 12000, "processing_ms": None, "total_ms": 12000}


def test_retry_queue_is_not_reported_as_actively_processing():
    from app.services.batch.timing import item_timings

    result = item_timings(
        created_at=CREATED, started_at=CREATED + timedelta(seconds=5), finished_at=None,
        status="queued", now=CREATED + timedelta(seconds=12),
    )
    assert result["processing_ms"] is None
    assert result["total_ms"] == 12000
