"""批次任务墙钟耗时；处理跨度包含重试等待，不等于模型推理耗时。"""

from datetime import datetime, timezone


def item_timings(
    *,
    created_at: datetime | None,
    started_at: datetime | None,
    finished_at: datetime | None,
    status: str,
    now: datetime,
) -> dict[str, int | None]:
    """兼容SQLite无时区UTC，缺失/矛盾时间保留未知，不把失败排除。"""
    unknown = {"queue_wait_ms": None, "processing_ms": None, "total_ms": None}

    def utc(value: datetime | None) -> datetime | None:
        return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value

    created, started, finished = map(utc, (created_at, started_at, finished_at))
    current = utc(now)
    if (created and started and started < created) or (
        finished and ((started and finished < started) or (created and finished < created))
    ):
        return unknown
    terminal = status in {"done", "review_required", "failed"}
    end = finished if terminal else current

    def elapsed(start: datetime | None, stop: datetime | None) -> int | None:
        if start is None or stop is None or stop < start:
            return None
        return round((stop - start).total_seconds() * 1000)

    return {
        "queue_wait_ms": elapsed(created, started if started else (None if terminal else current)),
        "processing_ms": None if status == "queued" else elapsed(started, end),
        "total_ms": elapsed(created, end),
    }
