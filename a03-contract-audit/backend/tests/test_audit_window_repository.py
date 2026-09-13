"""窗口检查点的持久化、隔离及迁移回归测试。"""
from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import Base
from app.llm.base import LLMResponse
from app.models import models
from app.services.audit.protocol import AgentReviewResult, ReviewIssue, ReviewedRiskCandidate
from app.services.audit.review_pipeline import ReviewWindow, WindowReviewRequest
from app.services.rag.contract_structure import ContractWindow


@pytest.fixture
def store(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'windows.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as db:
        db.add(models.User(id=1, username="窗口测试", password_hash="hash"))
        db.add(models.Contract(
            id=1, filename="contract.txt", storage_path="/contract.txt", uploaded_by=1,
        ))
    yield factory
    engine.dispose()


def request(**changes):
    return replace(WindowReviewRequest(
        contract_id=1, audit_job_id=10, audit_generation=2, agent="legal",
        dimensions=("payment", "liability"),
        review_window=ReviewWindow(
            ContractWindow(window_id="window-1", clause_ids=("clause-1",), text="合同正文"),
            parent_window_id="parent-1", depth=1,
        ),
        system_prompt="绝不存储的系统提示词",
        build_user_prompt=lambda *_: "绝不存储的用户提示词",
    ), **changes)


def result():
    return AgentReviewResult(
        complete=True,
        candidates=[ReviewedRiskCandidate(
            level="high", category="付款期限", quote="合同正文", reason="缺少明确期限",
            suggestion="补充付款期限",
            source_window_id="window-1", source_clause_ids=["clause-1"],
        )],
        issues=[ReviewIssue(code="EVIDENCE_UNRESOLVED", agent="legal", detail="需要补充证据")],
    )


def repository(factory, **kwargs):
    from app.services.audit.window_repository import SqlAlchemyWindowCheckpoint
    return SqlAlchemyWindowCheckpoint(session_factory=factory, **kwargs)


def test_models_define_window_identity_and_observation_fields(store):
    assert hasattr(models, "AuditWindowRun"), "缺少 AuditWindowRun 模型"
    inspector = inspect(store.kw["bind"])
    identity = {"audit_job_id", "audit_generation", "agent", "dimensions_hash", "window_id", "protocol_version"}
    assert any(set(c["column_names"]) == identity for c in inspector.get_unique_constraints("audit_window_runs"))
    indexes = {i["name"] for i in inspector.get_indexes("audit_window_runs")}
    assert {"ix_audit_window_runs_contract_id", "ix_audit_window_runs_audit_job_id"} <= indexes
    foreign_keys = inspector.get_foreign_keys("audit_window_runs")
    assert len(foreign_keys) == 1
    assert foreign_keys[0]["constrained_columns"] == ["contract_id"]
    assert foreign_keys[0]["options"]["ondelete"] == "CASCADE"
    logs = {c["name"] for c in inspector.get_columns("llm_call_logs")}
    assert {"window_id", "dimension", "attempt", "validation_status", "error_code"} <= logs
    assert not {"prompt", "response", "text", "system_prompt", "response_text"} & logs
    risks = {c["name"] for c in inspector.get_columns("risks")}
    assert {"secondary_review_status", "secondary_review_reason"} <= risks


def test_idempotent_save_restores_complete_result_from_new_repository(store):
    repo = repository(store)
    repo.save_valid(request(), result())
    repo.save_valid(request(), result())
    assert repository(store).load_valid(request()) == result()
    with store() as db:
        rows = db.scalars(select(models.AuditWindowRun)).all()
        assert len(rows) == 1
        assert rows[0].status == "valid"
        assert rows[0].parent_window_id == "parent-1"
        assert rows[0].depth == 1
        assert rows[0].attempts >= 1
        assert json.loads(rows[0].issues_json) == [issue.model_dump() for issue in result().issues]
        assert rows[0].created_at is not None and rows[0].updated_at is not None


@pytest.mark.parametrize("changes", [
    {"audit_job_id": 11}, {"audit_generation": 3}, {"agent": "finance"},
    {"dimensions": ("payment",)},
    {"review_window": ReviewWindow(ContractWindow("window-2", (), "另一条款"))},
])
def test_each_identity_field_is_isolated(store, changes):
    repo = repository(store)
    repo.save_valid(request(), result())
    assert repo.load_valid(request(**changes)) is None
    repo.save_valid(request(**changes), AgentReviewResult(complete=True))
    assert repo.load_valid(request()) == result()


def test_protocol_version_is_isolated(store):
    repository(store, protocol_version="candidate-v1").save_valid(request(), result())
    assert repository(store, protocol_version="candidate-v2").load_valid(request()) is None
    repository(store, protocol_version="candidate-v2").save_valid(request(), AgentReviewResult(complete=True))
    assert repository(store, protocol_version="candidate-v1").load_valid(request()) == result()


def test_default_repository_ignores_legacy_candidates_without_provenance(store):
    from app.services.audit.window_repository import dimensions_hash

    current_request = request()
    legacy_result = result().model_dump(mode="json")
    for candidate in legacy_result["candidates"]:
        candidate.pop("source_window_id")
        candidate.pop("source_clause_ids")
    legacy_json = json.dumps(legacy_result, ensure_ascii=False)
    with store.begin() as db:
        db.add(models.AuditWindowRun(
            contract_id=current_request.contract_id,
            audit_job_id=current_request.audit_job_id,
            audit_generation=current_request.audit_generation,
            agent=current_request.agent,
            dimensions_hash=dimensions_hash(current_request.dimensions),
            window_id=current_request.review_window.window.window_id,
            protocol_version="candidate-v1", status="valid",
            result_json=legacy_json, issues_json="[]", attempts=1,
        ))

    current_repository = repository(store)
    assert current_repository.load_valid(current_request) is None
    current_repository.save_valid(current_request, result())
    assert current_repository.load_valid(current_request) == result()
    with store() as db:
        rows = db.scalars(select(models.AuditWindowRun)).all()
        assert {row.protocol_version for row in rows} == {"candidate-v1", "candidate-v2"}
        legacy_row = next(row for row in rows if row.protocol_version == "candidate-v1")
        assert legacy_row.result_json == legacy_json


def test_dimensions_are_sorted_deduplicated_and_sha256_hashed(store):
    repo = repository(store)
    repo.save_valid(request(dimensions=("付款", "责任", "付款")), result())
    assert repo.load_valid(request(dimensions=("责任", "付款"))) == result()
    with store() as db:
        row = db.scalar(select(models.AuditWindowRun))
        normalized = json.dumps(sorted({"付款", "责任"}), ensure_ascii=False, separators=(",", ":"))
        assert row.dimensions_hash == hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def test_corrupt_valid_result_and_database_errors_propagate(store):
    repo = repository(store)
    repo.save_valid(request(), result())
    with store.begin() as db:
        db.scalar(select(models.AuditWindowRun)).result_json = "损坏的 JSON"
    with pytest.raises(ValidationError):
        repo.load_valid(request())
    with patch.object(Session, "execute", side_effect=OperationalError("查询", {}, Exception("数据库不可用"))):
        with pytest.raises(OperationalError):
            repo.load_valid(request())
        with pytest.raises(OperationalError):
            repo.save_valid(request(), result())


def test_only_valid_complete_checkpoints_are_reused(store):
    repo = repository(store)
    with pytest.raises(ValueError):
        repo.save_valid(request(), AgentReviewResult(complete=False))
    repo.save_valid(request(), result())
    with store.begin() as db:
        db.scalar(select(models.AuditWindowRun)).status = "failed"
    assert repo.load_valid(request()) is None


def test_synchronous_requests_do_not_open_sessions():
    def forbidden_session():
        pytest.fail("同步请求不得创建检查点事务")
    repo = repository(forbidden_session)
    sync_request = request(audit_job_id=None, contract_id=None)
    assert repo.load_valid(sync_request) is None
    repo.save_valid(sync_request, result())


def test_missing_contract_fails_explicitly_before_persistence(store):
    repo = repository(store)
    with pytest.raises(ValueError, match="contract_id"):
        repo.save_valid(request(contract_id=None), result())
    with pytest.raises(ValueError, match="contract_id"):
        repo.load_valid(request(contract_id=None))


def test_unique_insert_race_reloads_in_fresh_transaction(store):
    # 第一事务查无记录后，第二个独立事务先提交；第一事务随后真实触发唯一冲突。
    competitor = repository(store)
    original_execute = Session.execute
    raced = False
    database_errors = []
    event.listen(store.kw["bind"], "handle_error", lambda context: database_errors.append(context.original_exception))

    def insert_competitor(db, statement, *args, **kwargs):
        nonlocal raced
        rows = original_execute(db, statement, *args, **kwargs)
        if not raced and statement.is_select:
            raced = True
            competitor.save_valid(request(), AgentReviewResult(complete=True))
        return rows

    with patch.object(Session, "execute", insert_competitor):
        repository(store).save_valid(request(), result())
    assert raced
    assert len(database_errors) == 1
    assert "UNIQUE constraint failed" in str(database_errors[0])
    assert repository(store).load_valid(request()) == result()
    with store() as db:
        assert len(db.scalars(select(models.AuditWindowRun)).all()) == 1


def record(repo, req=None, **kwargs):
    options = dict(page=1, attempt=1, response=None, validation_status="error", error_code="MODEL_TIMEOUT")
    options.update(kwargs)
    repo.record_call(req or request(), **options)


def test_success_and_failed_calls_are_observable_without_response_text(store):
    repo = repository(store, provider="test-provider")
    record(repo, response=LLMResponse(
        text="秘密响应正文", model="test-model", prompt_tokens=12, completion_tokens=34,
        latency_ms=56, finish_reason="stop",
    ), validation_status="valid", error_code=None, attempt=2)
    record(repo, attempt=3)
    repo.save_valid(request(), result())
    repo.save_valid(request(), result())
    repository(store).save_valid(request(), result())
    with store() as db:
        success, failed = db.scalars(select(models.LLMCallLog).order_by(models.LLMCallLog.id)).all()
        assert (success.contract_id, success.audit_job_id, success.agent) == (1, 10, "legal")
        assert (success.window_id, success.dimension, success.attempt) == ("window-1", "liability,payment", 2)
        assert (success.provider, success.model, success.prompt_tokens, success.completion_tokens) == ("test-provider", "test-model", 12, 34)
        assert (success.finish_reason, success.latency_ms, success.mode, success.validation_status, success.error_code) == ("stop", 56, "llm", "valid", None)
        assert (failed.prompt_tokens, failed.completion_tokens, failed.model, failed.attempt) == (0, 0, "", 3)
        assert (failed.validation_status, failed.error_code) == ("error", "MODEL_TIMEOUT")
        assert db.scalar(select(models.AuditWindowRun)).attempts >= 2


def test_attempts_survive_repository_restart_before_checkpoint_save(store):
    first = repository(store)
    record(first)
    record(first)
    del first
    second = repository(store)
    with store() as db:
        row = db.scalar(select(models.AuditWindowRun))
        assert row is not None
        assert (row.status, row.result_json, row.issues_json, row.attempts) == ("failed", "{}", "[]", 2)
    assert second.load_valid(request()) is None
    record(second)
    second.save_valid(request(), result())
    second.save_valid(request(), result())
    with store() as db:
        rows = db.scalars(select(models.AuditWindowRun)).all()
        assert len(rows) == 1
        assert (rows[0].status, rows[0].attempts) == ("valid", 3)
        assert len(db.scalars(select(models.LLMCallLog)).all()) == 3


def test_save_with_stale_attempt_snapshot_does_not_lose_concurrent_call(store):
    repo = repository(store)
    record(repo)
    record(repo)
    competitor = repository(store)
    original_execute = Session.execute
    raced = False

    def record_after_snapshot(db, statement, *args, **kwargs):
        nonlocal raced
        rows = original_execute(db, statement, *args, **kwargs)
        if not raced and statement.is_select:
            snapshot = rows.freeze()
            raced = True
            record(competitor)
            return snapshot()
        return rows

    with patch.object(Session, "execute", record_after_snapshot):
        repo.save_valid(request(), result())
    assert raced
    repository(store).save_valid(request(), result())
    with store() as db:
        assert db.scalar(select(models.AuditWindowRun)).attempts == 3
        assert len(db.scalars(select(models.LLMCallLog)).all()) == 3


def test_record_call_retries_unique_conflict_without_duplicate_logs(store):
    competitor = repository(store)
    original_execute = Session.execute
    raced = False
    database_errors = []
    event.listen(store.kw["bind"], "handle_error", lambda context: database_errors.append(context.original_exception))

    def record_competitor(db, statement, *args, **kwargs):
        nonlocal raced
        rows = original_execute(db, statement, *args, **kwargs)
        if not raced and statement.is_select:
            snapshot = rows.freeze()
            raced = True
            record(competitor, attempt=1)
            return snapshot()
        return rows

    with patch.object(Session, "execute", record_competitor):
        record(repository(store), attempt=2)
    assert raced
    assert len(database_errors) == 1
    assert "UNIQUE constraint failed" in str(database_errors[0])
    with store() as db:
        windows = db.scalars(select(models.AuditWindowRun)).all()
        assert len(windows) == 1 and windows[0].attempts == 2
        assert db.scalars(select(models.LLMCallLog.attempt).order_by(models.LLMCallLog.id)).all() == [1, 2]


@pytest.mark.parametrize("dimensions", [(), ("payment",), ("x" * 64, "y" * 64)])
def test_call_dimension_is_stable_and_fits_column(store, dimensions):
    repo = repository(store)
    record(repo, request(dimensions=dimensions))
    record(repo, request(dimensions=tuple(reversed(dimensions)) + dimensions))
    with store() as db:
        first, second = db.scalars(select(models.LLMCallLog)).all()
        assert first.dimension == second.dimension
        assert len(first.dimension) <= 64
        if not dimensions:
            assert first.dimension == "all"
        if len(dimensions) == 1:
            assert first.dimension == dimensions[0]


def test_failed_log_commit_does_not_rollback_caller_transaction_or_leak_secrets(store):
    log_factory = sessionmaker(bind=store.kw["bind"])

    def fail_commit(db):
        raise RuntimeError("秘密连接字符串和响应正文")

    event.listen(log_factory, "before_commit", fail_commit)
    with store() as caller, patch("app.services.audit.window_repository.log") as logger:
        caller.add(models.User(username="调用方未提交数据", password_hash="hash"))
        record(repository(log_factory))
        assert caller.new and caller.is_active
        caller.commit()
        logger.warning.assert_called_once_with("audit.window_call_log_failed", exception_type="RuntimeError")
    with store() as db:
        assert db.scalar(select(models.User).where(models.User.username == "调用方未提交数据"))
        assert db.scalar(select(models.LLMCallLog)) is None
        assert db.scalar(select(models.AuditWindowRun)) is None


def test_migration_revision_and_sqlite_round_trip(tmp_path):
    path = Path(__file__).parents[1] / "alembic/versions/20260913_02_audit_window_reliability.py"
    assert path.is_file(), "缺少窗口可靠性迁移"
    spec = importlib.util.spec_from_file_location("window_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "20260913_02"
    assert migration.down_revision == "20260913_01"
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE contracts (id INTEGER PRIMARY KEY, status VARCHAR(32))")
        connection.exec_driver_sql("CREATE TABLE audit_batch_items (id INTEGER PRIMARY KEY, status VARCHAR(32))")
        connection.exec_driver_sql("CREATE TABLE risks (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE llm_call_logs (id INTEGER PRIMARY KEY, audit_job_id INTEGER, finish_reason VARCHAR(32))")
        connection.exec_driver_sql("INSERT INTO risks (id) VALUES (9)")
        connection.exec_driver_sql("INSERT INTO llm_call_logs (id, audit_job_id, finish_reason) VALUES (8, 10, 'stop')")
        for table in ("contracts", "audit_batch_items"):
            connection.exec_driver_sql(f"INSERT INTO {table} (id, status) VALUES (1, 'auditing'), (2, 'done')")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert inspect(connection).has_table("audit_window_runs")
            assert connection.exec_driver_sql(
                "SELECT secondary_review_status, secondary_review_reason FROM risks WHERE id = 9"
            ).one() == ("not_required", "")
            assert connection.exec_driver_sql(
                "SELECT dimension, attempt, validation_status FROM llm_call_logs WHERE id = 8"
            ).one() == ("all", 1, "unknown")
            for table in ("contracts", "audit_batch_items"):
                assert connection.execute(text(f"SELECT status FROM {table} ORDER BY id")).scalars().all() == ["reviewing", "done"]
            migration.downgrade()
            assert not inspect(connection).has_table("audit_window_runs")
            assert {c["name"] for c in inspect(connection).get_columns("llm_call_logs")} == {"id", "audit_job_id", "finish_reason"}
            assert {c["name"] for c in inspect(connection).get_columns("risks")} == {"id"}
            assert connection.exec_driver_sql("SELECT id FROM risks").scalar_one() == 9
            assert connection.exec_driver_sql("SELECT id, audit_job_id, finish_reason FROM llm_call_logs").one() == (8, 10, "stop")
            for table in ("contracts", "audit_batch_items"):
                assert connection.execute(text(f"SELECT status FROM {table} ORDER BY id")).scalars().all() == ["auditing", "done"]
            migration.upgrade()
    engine.dispose()
