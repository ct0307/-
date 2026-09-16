import json
from dataclasses import replace
from threading import Barrier, Lock

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


def test_two_windows_overlap_but_flush_in_source_order():
    state = _OverlapState()
    checkpoint = _RecordingCheckpoint()
    requests = [_request("window-1"), _request("window-2")]

    results = _review_window_requests(
        requests,
        checkpoint=checkpoint,
        adapter_factory=lambda: _BlockingAdapter(state),
        max_workers=2,
    )

    assert state.max_active == 2
    assert [item[0] for item in checkpoint.flushed] == ["window-1", "window-2"]
    assert len(results) == 2 and all(result.complete for result in results)


def test_concurrency_one_and_two_return_identical_results():
    class Adapter:
        def chat(self, *_args, **_kwargs):
            return LLMResponse(
                text=json.dumps({"risks": [], "has_more": False}),
                model="deterministic",
            )

    requests = [_request("window-1"), _request("window-2")]
    serial = _review_window_requests(
        requests,
        checkpoint=_RecordingCheckpoint(),
        adapter_factory=Adapter,
        max_workers=1,
    )
    parallel = _review_window_requests(
        requests,
        checkpoint=_RecordingCheckpoint(),
        adapter_factory=Adapter,
        max_workers=2,
    )

    assert parallel == serial


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
