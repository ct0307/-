import json
from dataclasses import replace
from threading import Barrier, Event, Lock, get_ident

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.core.config import Settings
from app.llm.base import LLMResponse
from app.models.models import AuditWindowRun, Contract, LLMCallLog, User
from app.services.audit.auditor import _review_window_requests
from app.services.audit.protocol import AgentReviewResult
from app.services.audit.review_pipeline import (
    BufferedWindowCheckpoint,
    ReviewWindow,
    WindowReviewRequest,
)
from app.services.audit.window_repository import SqlAlchemyWindowCheckpoint
from app.services.rag.contract_structure import ContractWindow


def _request(window_id: str) -> WindowReviewRequest:
    return WindowReviewRequest(
        contract_id=1,
        audit_job_id=10,
        audit_generation=1,
        agent="legal",
        dimensions=("legal",),
        review_window=ReviewWindow(ContractWindow(
            window_id=window_id,
            clause_ids=(window_id,),
            text=f"{window_id} 合同正文",
        )),
        system_prompt="system",
        build_user_prompt=lambda review_window, page, dimensions: (
            f"{review_window.window.window_id}:{page}:{','.join(dimensions)}"
        ),
    )


class _OverlapState:
    def __init__(self, parties=2):
        self.barrier = Barrier(parties)
        self.lock = Lock()
        self.active = 0
        self.max_active = 0


class _BlockingAdapter:
    def __init__(self, state: _OverlapState):
        self.state = state

    def chat(self, *_args, **_kwargs):
        with self.state.lock:
            self.state.active += 1
            self.state.max_active = max(self.state.max_active, self.state.active)
        self.state.barrier.wait(timeout=5)
        with self.state.lock:
            self.state.active -= 1
        return LLMResponse(
            text=json.dumps({"risks": [], "has_more": False}),
            model="concurrency-test",
        )


class _RecordingCheckpoint:
    def __init__(self):
        self.flushed = []

    def load_valid(self, _request):
        return None

    def flush_execution(self, request, execution):
        self.flushed.append((request.review_window.window.window_id, execution))


def test_fast_window_flushes_and_reports_before_slow_window_finishes():
    caller_thread = get_ident()
    slow_started = Event()
    slow_released = Event()
    callback_windows = []

    class Adapter:
        def chat(self, _system, user, **_kwargs):
            assert get_ident() != caller_thread
            if user.startswith("window-1:"):
                slow_started.set()
                assert slow_released.wait(timeout=5), (
                    "快窗口必须先落库并回调，才能释放慢窗口"
                )
            else:
                assert slow_started.wait(timeout=5)
            return LLMResponse(
                text='{"risks": [], "has_more": false}', model="completion-order"
            )

    class Checkpoint(_RecordingCheckpoint):
        def flush_execution(self, request, execution):
            assert get_ident() == caller_thread
            if request.review_window.window.window_id == "window-2":
                assert not slow_released.is_set()
            super().flush_execution(request, execution)

    checkpoint = Checkpoint()

    def completed():
        assert get_ident() == caller_thread
        callback_windows.append(checkpoint.flushed[-1][0])
        if callback_windows[-1] == "window-2":
            slow_released.set()

    requests = [_request("window-1"), _request("window-2")]
    results = _review_window_requests(
        requests,
        checkpoint=checkpoint,
        adapter_factory=Adapter,
        max_workers=2,
        window_completed_callback=completed,
    )

    assert [item[0] for item in checkpoint.flushed] == ["window-2", "window-1"]
    assert callback_windows == ["window-2", "window-1"]
    by_window = {window_id: execution.result for window_id, execution in checkpoint.flushed}
    assert results[0] is by_window["window-1"]
    assert results[1] is by_window["window-2"]
    assert len(results) == 2 and all(result.complete for result in results)


def test_cached_window_reports_before_uncached_work_starts():
    cached = AgentReviewResult(complete=True)
    cache_reported = Event()
    caller_thread = get_ident()
    reports = []

    class Checkpoint(_RecordingCheckpoint):
        def load_valid(self, request):
            assert get_ident() == caller_thread
            if request.review_window.window.window_id == "cached":
                return cached
            return None

    class Adapter:
        def chat(self, *_args, **_kwargs):
            assert cache_reported.is_set(), "缓存窗口应立即计入进度"
            return LLMResponse(text='{"risks": [], "has_more": false}', model="test")

    checkpoint = Checkpoint()

    def completed():
        assert get_ident() == caller_thread
        reports.append(len(checkpoint.flushed))
        cache_reported.set()

    results = _review_window_requests(
        [_request("uncached"), _request("cached")],
        checkpoint=checkpoint,
        adapter_factory=Adapter,
        max_workers=2,
        window_completed_callback=completed,
    )

    assert results[1] is cached
    assert reports == [0, 1]
    assert [item[0] for item in checkpoint.flushed] == ["uncached"]


@pytest.mark.parametrize("complete", [True, False])
def test_all_cached_windows_skip_model_calls_and_only_report_complete(complete):
    cached = AgentReviewResult(complete=complete)
    reports = []

    class Checkpoint(_RecordingCheckpoint):
        def load_valid(self, _request):
            return cached

    def forbidden_adapter():
        pytest.fail("缓存命中后不应调用模型")

    checkpoint = Checkpoint()
    results = _review_window_requests(
        [_request("cached-1"), _request("cached-2")],
        checkpoint=checkpoint,
        adapter_factory=forbidden_adapter,
        max_workers=2,
        window_completed_callback=lambda: reports.append(True),
    )

    assert results == [cached, cached]
    assert reports == ([True, True] if complete else [])
    assert checkpoint.flushed == []


def test_no_windows_does_not_access_checkpoint_or_model():
    def forbidden_call():
        pytest.fail("无窗口时不应访问模型或回调")

    assert _review_window_requests(
        [], checkpoint=object(), adapter_factory=forbidden_call, max_workers=0,
        window_completed_callback=forbidden_call,
    ) == []


def test_incomplete_window_flushes_without_reporting_completion():
    checkpoint = _RecordingCheckpoint()
    reports = []
    request = replace(_request("expired"), deadline=0)

    class Adapter:
        def chat(self, *_args, **_kwargs):
            pytest.fail("预算耗尽后不应调用模型")

    results = _review_window_requests(
        [request], checkpoint=checkpoint, adapter_factory=Adapter, max_workers=1,
        clock=lambda: 1, window_completed_callback=lambda: reports.append(True),
    )

    assert not results[0].complete
    assert results[0].issues[0].code == "AUDIT_DEADLINE_EXCEEDED"
    assert checkpoint.flushed[0][1].result is results[0]
    assert reports == []


@pytest.mark.parametrize("stage", ["load", "worker", "flush", "callback"])
def test_window_failures_propagate_without_reporting_before_flush(stage):
    failure = RuntimeError(f"{stage} 失败")
    reports = []

    class Checkpoint(_RecordingCheckpoint):
        def load_valid(self, _request):
            if stage == "load":
                raise failure
            return None

        def flush_execution(self, request, execution):
            if stage == "flush":
                raise failure
            super().flush_execution(request, execution)

    class Adapter:
        def chat(self, *_args, **_kwargs):
            if stage == "worker":
                raise failure
            return LLMResponse(text='{"risks": [], "has_more": false}', model="test")

    checkpoint = Checkpoint()

    def completed():
        assert len(checkpoint.flushed) == 1
        reports.append(True)
        raise failure

    with pytest.raises(RuntimeError) as caught:
        _review_window_requests(
            [_request("window-1")], checkpoint=checkpoint, adapter_factory=Adapter,
            max_workers=1, window_completed_callback=completed,
        )

    assert caught.value is failure
    assert reports == ([True] if stage == "callback" else [])


def test_concurrency_one_and_two_return_identical_results():
    class Adapter:
        def chat(self, *_args, **_kwargs):
            return LLMResponse(
                text=json.dumps({"risks": [], "has_more": False}),
                model="deterministic",
            )

    requests = [_request("window-1"), _request("window-2")]
    serial_checkpoint = _RecordingCheckpoint()
    serial_reports = []
    serial = _review_window_requests(
        requests,
        checkpoint=serial_checkpoint,
        adapter_factory=Adapter,
        max_workers=1,
        window_completed_callback=lambda: serial_reports.append(
            serial_checkpoint.flushed[-1][0]
        ),
    )
    parallel = _review_window_requests(
        requests,
        checkpoint=_RecordingCheckpoint(),
        adapter_factory=Adapter,
        max_workers=2,
    )

    assert parallel == serial
    assert [item[0] for item in serial_checkpoint.flushed] == ["window-1", "window-2"]
    assert serial_reports == ["window-1", "window-2"]


def test_real_sqlite_workers_do_not_write_and_main_flush_has_no_duplicates(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'contention.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as db:
        db.add(User(id=1, username="concurrency", password_hash="hash"))
        db.add(Contract(
            id=1,
            filename="contract.txt",
            storage_path="/contract.txt",
            uploaded_by=1,
        ))

    state = _OverlapState()
    requests = [_request("window-1"), _request("window-2")]
    checkpoint = SqlAlchemyWindowCheckpoint(session_factory=factory)
    try:
        results = _review_window_requests(
            requests,
            checkpoint=checkpoint,
            adapter_factory=lambda: _BlockingAdapter(state),
            max_workers=2,
        )
        with factory() as db:
            runs = db.scalars(select(AuditWindowRun).order_by(AuditWindowRun.window_id)).all()
            logs = db.scalars(select(LLMCallLog).order_by(LLMCallLog.window_id)).all()

        assert all(result.complete for result in results)
        assert [row.window_id for row in runs] == ["window-1", "window-2"]
        assert [row.window_id for row in logs] == ["window-1", "window-2"]
    finally:
        engine.dispose()


def test_buffered_child_observations_keep_child_window_identity(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'child-observation.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as db:
        db.add(User(id=1, username="child-window", password_hash="hash"))
        db.add(Contract(
            id=1, filename="contract.txt", storage_path="/contract.txt", uploaded_by=1
        ))
    parent = _request("parent")
    child = replace(
        parent,
        review_window=ReviewWindow(
            ContractWindow("child", ("child",), "child 合同正文"),
            parent_window_id="parent",
            depth=1,
        ),
    )
    buffer = BufferedWindowCheckpoint()
    response = LLMResponse(text='{"risks": [], "has_more": false}', model="test")
    buffer.record_call(
        child,
        page=1,
        attempt=1,
        response=response,
        validation_status="valid",
        error_code=None,
    )
    child_result = AgentReviewResult(complete=True)
    buffer.save_valid(child, child_result)
    execution = buffer.execution(AgentReviewResult(complete=False))
    try:
        SqlAlchemyWindowCheckpoint(session_factory=factory).flush_execution(
            parent, execution
        )
        with factory() as db:
            assert db.scalar(select(LLMCallLog)).window_id == "child"
            assert db.scalar(select(AuditWindowRun)).window_id == "child"
    finally:
        engine.dispose()


@pytest.mark.parametrize("value", [0, 4])
def test_model_concurrency_is_bounded(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, AUDIT_MODEL_CONCURRENCY=value)
