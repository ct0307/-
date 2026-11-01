"""真实模型阶段反馈及调度线程发布的回归验证。"""
import json
from dataclasses import replace
from threading import Barrier, Event, get_ident

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.db.session import Base
from app.llm.base import LLMError, LLMResponse
from app.models.models import AuditBatch, AuditBatchItem, Contract, User
from app.services.audit import auditor
from app.services.audit.progress import publish_progress
from app.services.audit.review_pipeline import (
    NullWindowCheckpoint,
    ReviewWindow,
    WindowReviewer,
    WindowReviewRequest,
    enrichment_candidate_id,
)
from app.services.audit.protocol import RiskFinding
from app.services.rag.contract_structure import ContractWindow


def _response(payload):
    return LLMResponse(text=json.dumps(payload), model="stage-test")


def _request():
    return WindowReviewRequest(
        contract_id=None, audit_job_id=None, audit_generation=1,
        agent="legal", dimensions=("legal",),
        review_window=ReviewWindow(ContractWindow("window-1", ("第一条",), "付款期限未约定。")),
        system_prompt="legacy", build_user_prompt=lambda *_args: "legacy",
        discovery_system_prompt="discovery", build_discovery_prompt=lambda *_args: "discovery",
        enrichment_system_prompt="enrichment", build_enrichment_prompt=lambda *_args: "enrichment",
    )


@pytest.mark.parametrize("outcome", ["normal", "empty", "error"])
def test_real_stages_arrive_before_window_finishes_on_scheduler_thread(outcome):
    scheduler_thread = get_ident()
    received = {stage: Event() for stage in ("discovering", "enriching")}
    reports = []
    completions = []

    class Adapter:
        def chat(self, system, *_args, **_kwargs):
            assert get_ident() != scheduler_thread
            stage = "discovering" if system == "discovery" else "enriching"
            assert received[stage].wait(timeout=3), "模型返回前必须由调度线程发布真实阶段"
            if outcome == "error":
                raise LLMError("供应商拒绝", code="MODEL_REJECTED", retryable=False)
            if system == "discovery":
                findings = [] if outcome == "empty" else [
                    {"level": "high", "category": "付款风险", "quote": "付款期限未约定。"},
                ]
                return _response({"risks": findings, "has_more": False})
            return _response({"reason": "付款日期不明确。", "suggestion": "约定付款日期。"})

    def report(stage):
        assert get_ident() == scheduler_thread
        assert not completions, "内部阶段必须先于窗口完成事件"
        reports.append(stage)
        received[stage].set()

    results = auditor._review_window_requests(
        [_request()], checkpoint=NullWindowCheckpoint(), adapter_factory=Adapter,
        max_workers=1, stage_callback=report,
        window_completed_callback=lambda: completions.append(True),
    )

    assert reports == (["discovering", "enriching"] if outcome == "normal" else ["discovering"])
    assert results[0].complete is (outcome != "error")
    assert completions == ([] if outcome == "error" else [True])


def test_reviewer_deduplicates_same_stage_across_enrichment_items_and_retries():
    stages = []
    systems = []
    responses = iter([
        _response({"risks": [
            {"level": "high", "category": "付款风险", "quote": "付款期限未约定。"},
            {"level": "medium", "category": "验收风险", "quote": "验收标准未约定。"},
        ], "has_more": False}),
        _response({}),
        _response({"reason": "付款日期不明确。", "suggestion": "约定付款日期。"}),
        _response({"reason": "验收标准不明确。", "suggestion": "约定验收标准。"}),
    ])

    class Adapter:
        def chat(self, system, *_args, **_kwargs):
            systems.append(system)
            assert stages[-1] == ("discovering" if system == "discovery" else "enriching")
            return next(responses)

    result = WindowReviewer(Adapter(), stage_callback=stages.append).review(_request())

    assert result.complete
    assert len(result.candidates) == 2
    assert systems == ["discovery", "enrichment", "enrichment", "enrichment"]
    assert stages == ["discovering", "enriching"]


def test_expired_window_does_not_report_model_activity():
    stages = []

    class Adapter:
        def chat(self, *_args, **_kwargs):
            pytest.fail("时限到达后不应调用模型")

    result = WindowReviewer(
        Adapter(), clock=lambda: 1, stage_callback=stages.append,
    ).review(replace(_request(), deadline=0))

    assert result.issues[0].code == "AUDIT_DEADLINE_EXCEEDED"
    assert stages == []


def test_batch_enrichment_reports_stage_before_call_and_keeps_candidate_order(monkeypatch):
    monkeypatch.setattr(auditor.settings, "AUDIT_BATCH_ENRICHMENT_ENABLED", True)
    stages = []
    finding = RiskFinding(level="high", category="付款风险", quote="付款期限未约定。")
    request = replace(_request(), build_enrichment_batch_prompt=lambda *_args: "batch")

    class Adapter:
        def chat(self, system, *_args, **_kwargs):
            if system == "discovery":
                assert stages == ["discovering"]
                return _response({"risks": [finding.model_dump()], "has_more": False})
            assert stages == ["discovering", "enriching"]
            return _response({"items": [{
                "candidate_id": enrichment_candidate_id("window-1", finding),
                "reason": "付款日期不明确。", "suggestion": "约定付款日期。",
            }]})

    result = WindowReviewer(Adapter(), stage_callback=stages.append).review(request)
    assert result.complete and len(result.candidates) == 1
    assert result.candidates[0].quote == finding.quote


def test_parallel_windows_coalesce_identical_stage_notifications():
    stages = []
    received = Event()
    overlap = Barrier(2)
    scheduler_thread = get_ident()

    class Adapter:
        def chat(self, *_args, **_kwargs):
            overlap.wait(timeout=3)
            assert received.wait(timeout=3)
            return _response({"risks": [], "has_more": False})

    def report(stage):
        assert get_ident() == scheduler_thread
        stages.append(stage)
        received.set()

    request = _request()
    results = auditor._review_window_requests(
        [request, replace(request, review_window=ReviewWindow(ContractWindow("window-2", (), "正文")))],
        checkpoint=NullWindowCheckpoint(), adapter_factory=Adapter, max_workers=2,
        stage_callback=report,
    )
    assert stages == ["discovering"]
    assert len(results) == 2 and all(result.complete for result in results)


def test_audit_enters_review_before_first_model_and_only_completed_windows_raise_percentage(monkeypatch):
    reports = []

    class Adapter:
        def chat(self, *_args, **_kwargs):
            return _response({"risks": [], "has_more": False})

    def retrieve(*_args, **_kwargs):
        assert reports == [(15, "reviewing")], "候选准备前必须离开解析阶段"
        return []

    monkeypatch.setattr(auditor, "retrieve", retrieve)
    monkeypatch.setattr(auditor, "get_llm_adapter", Adapter)
    result = auditor.audit_contract(
        {}, "第一条 合同正文", dimensions=["legal"],
        progress_callback=lambda value, stage: reports.append((value, stage)),
    )

    assert reports == [
        (15, "reviewing"), (15, "discovering"),
        (75, "reviewing"), (82, "verifying"), (90, "verifying"),
    ]
    assert result["coverage"] == {"planned": 1, "completed": 1}


@pytest.mark.parametrize("stage", ["discovering", "enriching"])
def test_stage_publication_preserves_execution_fence_and_monotonic_percentage(tmp_path, stage):
    engine = create_engine(f"sqlite:///{tmp_path / 'stage.db'}")
    Base.metadata.create_all(engine)
    scheduler_thread = get_ident()
    write_threads = []

    @event.listens_for(engine, "before_cursor_execute")
    def capture_write(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.startswith("UPDATE audit_batch_items"):
            write_threads.append(get_ident())

    try:
        with Session(engine) as db:
            db.add(User(id=1, username="stage", password_hash="hash"))
            db.add(Contract(id=1, filename="stage.txt", storage_path="/stage.txt", uploaded_by=1))
            db.add(AuditBatch(id=1, owner_id=1, department="法务部", total=1,
                              idempotency_key="stage", request_fingerprint="a" * 64))
            db.flush()
            db.add(AuditBatchItem(id=1, batch_id=1, contract_id=1, filename="stage.txt",
                                  status="reviewing", audit_generation=2, execution_token="current",
                                  progress=40, progress_stage="reviewing"))
            db.commit()
            identity = dict(item_id=1, contract_id=1, generation=2, execution_token="current")
            assert publish_progress(db, **identity, progress=15, stage=stage)
            assert not publish_progress(db, **identity, progress=15, stage=stage)
            for override in ({"generation": 1}, {"execution_token": "stale"}):
                assert not publish_progress(db, **(identity | override), progress=80, stage="reviewing")
            saved = db.get(AuditBatchItem, 1)
            assert (saved.progress, saved.progress_stage) == (40, stage)
            saved.status = "done"
            db.commit()
            assert not publish_progress(db, **identity, progress=90, stage="reviewing")
            db.refresh(saved)
            assert (saved.progress, saved.progress_stage) == (40, stage)
        assert write_threads and set(write_threads) == {scheduler_thread}
    finally:
        engine.dispose()
