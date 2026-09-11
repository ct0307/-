import unittest
from importlib.util import find_spec
from unittest.mock import patch

from sqlalchemy import create_engine, event, func, inspect, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.v1.endpoints import contracts, risks, runtime
from app.db import init_db as init_db_module
from app.db.session import Base
from app.models.models import Contract, Risk, User
from app.schemas.contract import RiskStatusUpdate
from app.tasks.audit_tasks import run_contract_audit
from scripts import migrate_sqlite_to_postgres


class MergeReadinessTests(unittest.TestCase):
    def test_contract_audit_status_route_returns_persisted_result(self):
        route = next(
            (
                item
                for item in contracts.router.routes
                if item.path == "/{contract_id}/audit-status" and "GET" in item.methods
            ),
            None,
        )
        self.assertIsNotNone(route)
        if route is None:
            return

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                user = User(
                    username="legal",
                    password_hash="hash",
                    role="legal",
                    department="法务部",
                )
                db.add(user)
                db.flush()
                contract = Contract(
                    filename="contract.pdf",
                    storage_path="/contract.pdf",
                    department=user.department,
                    uploaded_by=user.id,
                    status="review_required",
                    requires_review=True,
                    review_reason="OCR 结果需要人工复核",
                )
                db.add(contract)
                db.flush()
                db.add(Risk(
                    contract_id=contract.id,
                    agent="system",
                    level="high",
                    category="OCR 质量",
                    original_text="扫描文本",
                    basis="置信度不足",
                    suggestion="人工复核",
                    confidence=42,
                    tier="red",
                    review_status="pending",
                    rag_sources="[]",
                ))
                db.commit()

                response = route.endpoint(contract.id, db=db, user=user)

                self.assertEqual(response.status, "review_required")
                self.assertEqual(response.risk_count, 1)
                self.assertTrue(response.requires_review)
                self.assertEqual(response.review_reason, "OCR 结果需要人工复核")
        finally:
            engine.dispose()

    def test_final_audit_retry_persists_failed_contract_status(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                user = User(
                    username="legal-failure",
                    password_hash="hash",
                    role="legal",
                    department="legal",
                )
                db.add(user)
                db.flush()
                contract = Contract(
                    filename="contract.pdf",
                    storage_path="/contract.pdf",
                    department=user.department,
                    uploaded_by=user.id,
                    status="auditing",
                )
                db.add(contract)
                db.commit()
                contract_id = contract.id

            run_contract_audit.push_request(retries=run_contract_audit.max_retries)
            try:
                with (
                    patch("app.tasks.audit_tasks.SessionLocal", lambda: Session(engine)),
                    patch("app.tasks.audit_tasks.run_audit", side_effect=RuntimeError("boom")),
                ):
                    with self.assertRaises(RuntimeError):
                        run_contract_audit.run(contract_id, [])
            finally:
                run_contract_audit.pop_request()

            with Session(engine) as db:
                saved = db.get(Contract, contract_id)
                self.assertIsNotNone(saved)
                self.assertEqual(saved.status, "audit_failed")
        finally:
            engine.dispose()

    def test_sqlite_hot_migration_adds_ocr_quality_columns(self):
        engine = create_engine("sqlite:///:memory:")
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "CREATE TABLE contracts (id INTEGER PRIMARY KEY, elements_json TEXT)"
                )

            with (
                patch.object(init_db_module, "engine", engine),
                patch.object(init_db_module.settings, "DB_BACKEND", "sqlite"),
            ):
                init_db_module._migrate_dev_columns()

            columns = {column["name"] for column in inspect(engine).get_columns("contracts")}
            self.assertTrue(
                {"parse_source", "ocr_confidence", "requires_review", "review_reason"}
                <= columns
            )
        finally:
            engine.dispose()

    def test_sqlite_hot_migration_keeps_execution_token_on_batch_items(self):
        contract_columns = dict(init_db_module._DEV_COLUMNS["contracts"])
        item_columns = dict(init_db_module._DEV_COLUMNS["audit_batch_items"])

        self.assertNotIn("execution_token", contract_columns)
        self.assertEqual(item_columns["execution_token"], "VARCHAR(64)")

    def test_finishing_last_pending_risk_completes_manual_review(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                user = User(
                    username="legal-review",
                    password_hash="hash",
                    role="legal",
                    department="legal",
                )
                db.add(user)
                db.flush()
                contract = Contract(
                    filename="contract.pdf",
                    storage_path="/contract.pdf",
                    department=user.department,
                    uploaded_by=user.id,
                    status="review_required",
                    requires_review=True,
                    review_reason="OCR result requires review",
                )
                db.add(contract)
                db.flush()
                risk = Risk(
                    contract_id=contract.id,
                    agent="system",
                    level="high",
                    category="OCR quality",
                    original_text="scan",
                    basis="low confidence",
                    suggestion="manual review",
                    confidence=42,
                    tier="red",
                    review_status="pending",
                    rag_sources="[]",
                )
                db.add(risk)
                db.commit()
                contract_id = contract.id
                risk_id = risk.id

                with patch("app.api.v1.endpoints.risks.audit_log.record"):
                    risks.update_risk_status(
                        risk_id,
                        RiskStatusUpdate(review_status="confirmed"),
                        db=db,
                        user=user,
                    )

                db.expire_all()
                saved = db.get(Contract, contract_id)
                self.assertIsNotNone(saved)
                self.assertFalse(saved.requires_review)
                self.assertIsNone(saved.review_reason)
                self.assertEqual(saved.status, "done")
        finally:
            engine.dispose()

    def test_runtime_status_route_requires_authentication(self):
        route = next(item for item in runtime.router.routes if item.path == "/status")
        dependency_calls = {dependency.call for dependency in route.dependant.dependencies}
        self.assertIn(get_current_user, dependency_calls)

    def test_runtime_probe_is_cached_and_public_response_includes_safe_diagnostics(self):
        get_cached_status = getattr(runtime, "_get_cached_runtime_status", None)
        self.assertIsNotNone(get_cached_status)
        if get_cached_status is None:
            return

        calls = 0

        def fake_probe():
            nonlocal calls
            calls += 1
            return {"model": "qwen"}

        with (
            patch.object(runtime, "probe_configured_model", fake_probe),
            patch.object(runtime.settings, "LLM_BASE_URL", "http://user:secret@internal:11434/v1?token=secret"),
        ):
            runtime._runtime_status_cache.clear()
            first = get_cached_status(now=100.0)
            second = get_cached_status(now=110.0)

        self.assertEqual(calls, 1)
        self.assertEqual(first, second)
        self.assertEqual(first.endpoint, "http://internal:11434/v1")
        self.assertIsNone(first.error_code)
        self.assertIsInstance(first.latency_ms, int)
        self.assertEqual(first.last_success_at, first.checked_at)

    def test_sqlite_to_postgres_migration_command_exists(self):
        self.assertIsNotNone(find_spec("scripts.migrate_sqlite_to_postgres"))

    def test_data_migration_copies_rows_and_verifies_counts(self):
        migrate_data = getattr(migrate_sqlite_to_postgres, "migrate_data", None)
        self.assertIsNotNone(migrate_data)
        if migrate_data is None:
            return

        source = create_engine("sqlite:///:memory:")
        target = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(source)
        Base.metadata.create_all(target)
        try:
            with source.begin() as connection:
                connection.execute(User.__table__.insert().values(
                    id=1,
                    username="migrated-user",
                    password_hash="hash",
                    role="legal",
                    department="legal",
                ))

            counts = migrate_data(source, target, tables=[User.__table__])

            self.assertEqual(counts, {"users": 1})
            with target.connect() as connection:
                self.assertEqual(
                    connection.scalar(select(func.count()).select_from(User.__table__)),
                    1,
                )
        finally:
            source.dispose()
            target.dispose()

    def test_data_migration_rolls_back_all_tables_on_failure(self):
        migrate_data = getattr(migrate_sqlite_to_postgres, "migrate_data", None)
        self.assertIsNotNone(migrate_data)
        if migrate_data is None:
            return

        source = create_engine("sqlite:///:memory:")
        target = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(source)
        Base.metadata.create_all(target)
        try:
            with source.begin() as connection:
                connection.execute(User.__table__.insert().values(
                    id=1,
                    username="rollback-user",
                    password_hash="hash",
                    role="legal",
                    department="legal",
                ))
                connection.execute(Contract.__table__.insert().values(
                    id=1,
                    filename="contract.pdf",
                    storage_path="/contract.pdf",
                    department="legal",
                    uploaded_by=1,
                ))

            def fail_contract_insert(_conn, _cursor, statement, _parameters, _context, _many):
                if statement.lstrip().upper().startswith("INSERT INTO CONTRACTS"):
                    raise RuntimeError("target insert failed")

            event.listen(target, "before_cursor_execute", fail_contract_insert)
            with self.assertRaises(RuntimeError):
                migrate_data(
                    source,
                    target,
                    tables=[User.__table__, Contract.__table__],
                )

            with target.connect() as connection:
                self.assertEqual(
                    connection.scalar(select(func.count()).select_from(User.__table__)),
                    0,
                )
        finally:
            source.dispose()
            target.dispose()


if __name__ == "__main__":
    unittest.main()
