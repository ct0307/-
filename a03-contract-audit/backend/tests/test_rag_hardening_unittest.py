import asyncio
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.api.v1.endpoints import knowledge
from app.api.v1.endpoints.knowledge import _MAX_CHUNK_CHARS, _smart_split
from app.db import init_db
from app.llm.base import LLMError
from app.llm.adapters.local_embedding import LocalEmbeddingAdapter
from app.models import models as app_models
from app.models.models import KnowledgeChunk
from app.schemas.contract import KnowledgeImport
from app.services.rag import retriever
from scripts import seed_demo


class _FakeEmbeddingAdapter:
    def __init__(self, vectors):
        self._vectors = vectors

    def embed(self, _texts):
        return self._vectors


class _FakeDb:
    def __init__(self):
        self.added = []
        self.commits = 0

    def add(self, row):
        self.added.append(row)

    def commit(self):
        self.commits += 1


class _FakeUpload:
    filename = "large.txt"

    def __init__(self, content: bytes):
        self._content = content

    async def read(self):
        return self._content


class RagHardeningTests(unittest.TestCase):
    def tearDown(self):
        retriever._bm25_cache = None

    def test_knowledge_scope_defaults_to_unclassified(self):
        engine = create_engine("sqlite:///:memory:")
        KnowledgeChunk.__table__.create(engine)
        db = sessionmaker(bind=engine)()
        try:
            chunk = KnowledgeChunk(category="law", source="unknown", content="text")
            db.add(chunk)
            db.flush()

            self.assertEqual(chunk.scope_mode, "unclassified")
        finally:
            db.close()
            engine.dispose()

    def test_dev_schema_contains_scope_mode_backfill(self):
        columns = dict(init_db._DEV_COLUMNS["knowledge_chunks"])

        self.assertIn("scope_mode", columns)
        self.assertIn("unclassified", columns["scope_mode"])

    def test_legal_source_models_and_dev_columns_are_declared(self):
        self.assertTrue(hasattr(app_models, "LegalSource"))
        self.assertTrue(hasattr(app_models, "LegalArticle"))
        columns = dict(init_db._DEV_COLUMNS["knowledge_chunks"])
        self.assertEqual(
            {
                "legal_article_id",
                "chunk_index",
                "chunk_count",
                "chunk_schema_version",
                "retrieval_text",
                "embedding_signature",
            }
            - columns.keys(),
            set(),
        )

    def test_vector_search_rejects_below_similarity_threshold(self):
        docs = [(
            1, "无关内容", "来源", json.dumps([0.0, 1.0]), "law", None, None,
            None, None, "[]", "[]", retriever.settings.LOCAL_EMBED_MODEL, 2,
        )]
        adapter = _FakeEmbeddingAdapter([[1.0, 0.0]])

        with patch.object(retriever, "get_embedding_adapter", return_value=adapter):
            result = retriever._vector_search("违约责任", docs)

        self.assertEqual(result, {})

    def test_vector_search_skips_dimension_mismatch(self):
        docs = [(
            1, "旧模型向量", "来源", json.dumps([1.0, 0.0, 0.0]), "law", None, None,
            None, None, "[]", "[]", retriever.settings.LOCAL_EMBED_MODEL, 3,
        )]
        adapter = _FakeEmbeddingAdapter([[1.0, 0.0]])

        with patch.object(retriever, "get_embedding_adapter", return_value=adapter):
            result = retriever._vector_search("查询", docs)

        self.assertEqual(result, {})

    def test_vector_search_skips_embedding_model_mismatch(self):
        docs = [(
            1, "旧模型向量", "来源", json.dumps([1.0, 0.0]), "law", None, None,
            None, None, "[]", "[]", "stale-model", 2,
        )]
        adapter = _FakeEmbeddingAdapter([[1.0, 0.0]])

        with patch.object(retriever, "get_embedding_adapter", return_value=adapter):
            with patch.object(retriever.settings, "EMBED_BACKEND", "local"):
                with patch.object(retriever.settings, "LOCAL_EMBED_MODEL", "current-model"):
                    result = retriever._vector_search("查询", docs)

        self.assertEqual(result, {})

    def test_index_documents_rejects_vector_count_mismatch(self):
        chunks = [{"content": "第一条"}, {"content": "第二条"}]
        db = _FakeDb()
        adapter = _FakeEmbeddingAdapter([[1.0, 0.0]])

        with patch.object(retriever, "get_embedding_adapter", return_value=adapter):
            with self.assertRaisesRegex(LLMError, "数量"):
                retriever.index_documents(chunks, db=db)

        self.assertEqual(db.added, [])
        self.assertEqual(db.commits, 0)

    def test_prepare_documents_defaults_to_unclassified_scope(self):
        adapter = _FakeEmbeddingAdapter([[1.0, 0.0]])

        with patch.object(retriever, "get_embedding_adapter", return_value=adapter):
            rows = retriever.prepare_documents([{"content": "legacy knowledge"}])

        self.assertEqual(rows[0].scope_mode, "unclassified")

    def test_prepare_documents_rejects_scoped_without_targets_before_embedding(self):
        with patch.object(retriever, "get_embedding_adapter") as get_adapter:
            with self.assertRaisesRegex(ValueError, "contract type or audit dimension"):
                retriever.prepare_documents([
                    {"content": "invalid scoped knowledge", "scope_mode": "scoped"}
                ])

        get_adapter.assert_not_called()

    def test_knowledge_import_schema_rejects_invalid_scope_combination(self):
        with self.assertRaises(ValidationError):
            KnowledgeImport(content="invalid scoped knowledge", scope_mode="scoped")

    def test_file_scope_form_parses_json_lists_and_rejects_empty_scoped_target(self):
        parsed = knowledge._parse_scope_form("scoped", '["采购合同"]', '["payment"]')
        self.assertEqual(parsed["applicable_contract_types"], ["采购合同"])
        self.assertEqual(parsed["applicable_dimensions"], ["payment"])

        with self.assertRaises(HTTPException) as context:
            knowledge._parse_scope_form("scoped", "[]", "[]")

        self.assertEqual(context.exception.status_code, 422)

    def test_controlled_seed_scope_metadata_is_explicit(self):
        civil_code = retriever.controlled_seed_scope("law", "《民法典》第577条")
        software = retriever.controlled_seed_scope(
            "template", "软件开发外包合同标准知识产权条款"
        )
        purchase = retriever.controlled_seed_scope("template", "采购合同标准付款条款")
        unknown = retriever.controlled_seed_scope("law", "未知旧法规")

        self.assertEqual(civil_code["scope_mode"], "global")
        self.assertEqual(software["scope_mode"], "scoped")
        self.assertIn("软件开发外包合同", software["applicable_contract_types"])
        self.assertEqual(purchase["scope_mode"], "scoped")
        self.assertIn("采购合同", purchase["applicable_contract_types"])
        self.assertEqual(unknown["scope_mode"], "unclassified")

    def test_demo_seed_persists_explicit_knowledge_scope(self):
        engine = create_engine("sqlite:///:memory:")
        KnowledgeChunk.__table__.create(engine)
        db = sessionmaker(bind=engine)()
        try:
            seed_demo.seed_knowledge(db)
            civil_code = db.query(KnowledgeChunk).filter(
                KnowledgeChunk.source == "《民法典》第577条"
            ).one()
            software_case = db.query(KnowledgeChunk).filter(
                KnowledgeChunk.source == "软件外包合同知识产权归属案例"
            ).one()

            self.assertEqual(civil_code.scope_mode, "global")
            self.assertEqual(software_case.scope_mode, "scoped")
        finally:
            db.close()
            engine.dispose()

    def test_bm25_cache_invalidates_when_content_changes(self):
        first = [(1, "违约责任", "来源", "")]
        changed = [(1, "付款验收", "来源", "")]

        old_index = retriever._get_bm25_index(first)[0]
        new_index = retriever._get_bm25_index(changed)[0]

        self.assertIsNot(new_index, old_index)

    def test_fallback_rules_are_marked_as_internal_rules(self):
        results = retriever._keyword_search("争议 仲裁 管辖", top_k=3)

        self.assertTrue(results)
        self.assertTrue(all(item["source_type"] == "fallback_rule" for item in results))
        self.assertTrue(all(item["reliable"] is False for item in results))
        self.assertTrue(all("民法典" not in item["source"] for item in results))

    def test_article_number_is_extracted_from_chunk_content(self):
        content = "【第三编 合同】\n第五百八十五条 当事人可以约定违约金。"

        self.assertEqual(retriever._extract_article_number(content), "第五百八十五条")

    def test_alembic_history_loads_rag_metadata_revision(self):
        backend_dir = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "alembic", "-c", "alembic.ini", "history"],
            cwd=backend_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("20260726_rag_metadata", result.stdout)

    def test_alembic_upgrades_and_downgrades_fresh_database(self):
        backend_dir = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "migration-smoke.db"
            env = os.environ.copy()
            env.update({"DB_BACKEND": "sqlite", "SQLITE_PATH": database.as_posix()})

            upgrade = subprocess.run(
                [sys.executable, "-X", "utf8", "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
                cwd=backend_dir,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(upgrade.returncode, 0, upgrade.stdout + upgrade.stderr)

            engine = create_engine(f"sqlite:///{database.as_posix()}")
            migrated_tables = set(inspect(engine).get_table_names()) - {"alembic_version"}
            self.assertEqual(migrated_tables, set(KnowledgeChunk.metadata.tables))
            engine.dispose()

            downgrade = subprocess.run(
                [sys.executable, "-X", "utf8", "-m", "alembic", "-c", "alembic.ini", "downgrade", "base"],
                cwd=backend_dir,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(downgrade.returncode, 0, downgrade.stdout + downgrade.stderr)

            engine = create_engine(f"sqlite:///{database.as_posix()}")
            remaining_tables = set(inspect(engine).get_table_names()) - {"alembic_version"}
            self.assertEqual(remaining_tables, set())
            engine.dispose()

    def test_scope_migration_backfills_only_controlled_sources(self):
        backend_dir = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "scope-backfill.db"
            env = os.environ.copy()
            env.update({"DB_BACKEND": "sqlite", "SQLITE_PATH": database.as_posix()})
            previous = subprocess.run(
                [sys.executable, "-X", "utf8", "-m", "alembic", "-c", "alembic.ini", "upgrade", "20260726_02"],
                cwd=backend_dir, env=env, capture_output=True, text=True, encoding="utf-8", check=False,
            )
            self.assertEqual(previous.returncode, 0, previous.stdout + previous.stderr)

            engine = create_engine(f"sqlite:///{database.as_posix()}")
            with engine.begin() as connection:
                for source in (
                    "《民法典》第577条",
                    "软件开发外包合同标准知识产权条款",
                    "未知旧法规",
                ):
                    connection.execute(text(
                        "INSERT INTO knowledge_chunks "
                        "(category, source, content, embedding, applicable_contract_types, "
                        "applicable_dimensions) VALUES "
                        "('law', :source, 'content', '', '[]', '[]')"
                    ), {"source": source})
            engine.dispose()

            upgrade = subprocess.run(
                [sys.executable, "-X", "utf8", "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
                cwd=backend_dir, env=env, capture_output=True, text=True, encoding="utf-8", check=False,
            )
            self.assertEqual(upgrade.returncode, 0, upgrade.stdout + upgrade.stderr)

            engine = create_engine(f"sqlite:///{database.as_posix()}")
            with engine.connect() as connection:
                rows = dict(connection.execute(text(
                    "SELECT source, scope_mode FROM knowledge_chunks"
                )).all())
            engine.dispose()

            self.assertEqual(rows["《民法典》第577条"], "global")
            self.assertEqual(rows["软件开发外包合同标准知识产权条款"], "scoped")
            self.assertEqual(rows["未知旧法规"], "unclassified")

    def test_filter_docs_applies_contract_dimension_category_and_date(self):
        docs = [
            (
                1, "采购付款规则", "采购制度", "", "rule", "第一条", "2026",
                date(2026, 1, 1), None, '["采购合同"]', '["payment"]', None, None,
                "scoped",
            ),
            (
                2, "劳动争议规则", "劳动制度", "", "rule", "第二条", "2026",
                date(2026, 1, 1), None, '["劳动合同"]', '["legal"]', None, None,
                "scoped",
            ),
            (
                3, "已失效采购规则", "旧制度", "", "rule", "第三条", "2020",
                date(2020, 1, 1), date(2025, 12, 31), '["采购合同"]', '["payment"]', None, None,
                "scoped",
            ),
            (
                4, "无范围限制法规", "通用法规", "", "law", "第四条", None,
                None, None, "[]", "[]", None, None, "global",
            ),
        ]

        result = retriever._filter_docs(
            docs,
            contract_type="采购合同",
            dimensions=["payment"],
            categories=["rule", "law"],
            as_of=date(2026, 7, 26),
        )

        self.assertEqual([doc[0] for doc in result], [1, 4])

    def test_filter_docs_rejects_unclassified_and_scoped_without_targets(self):
        docs = [
            (1, "unknown", "legacy", "", "law", None, None, None, None,
             "[]", "[]", None, None, "unclassified"),
            (2, "missing scope", "template", "", "template", None, None, None, None,
             "[]", "[]", None, None, "scoped"),
            (3, "civil code", "controlled law", "", "law", None, None, None, None,
             "[]", "[]", None, None, "global"),
        ]

        result = retriever._filter_docs(
            docs,
            contract_type="purchase",
            dimensions=["payment"],
        )

        self.assertEqual([doc[0] for doc in result], [3])

    def test_filter_docs_rejects_cross_domain_scoped_document(self):
        docs = [
            (1, "software acceptance", "software template", "", "template", None, None,
             None, None, '["software"]', '["acceptance"]', None, None, "scoped"),
            (2, "purchase payment", "purchase template", "", "template", None, None,
             None, None, '["purchase"]', '["payment"]', None, None, "scoped"),
        ]

        result = retriever._filter_docs(
            docs,
            contract_type="purchase",
            dimensions=["payment"],
        )

        self.assertEqual([doc[0] for doc in result], [2])

    def test_bm25_search_rejects_zero_score_documents(self):
        docs = [(1, "alpha beta", "source", ""), (2, "gamma delta", "source", "")]

        result = retriever._bm25_search("unrelated", docs)

        self.assertEqual(result, {})

    def test_single_long_sentence_is_hard_split(self):
        text = "第一条 " + "甲" * 900 + "\n第二条 " + "乙" * 30

        result = _smart_split(text)

        self.assertTrue(result.chunks)
        self.assertTrue(all(len(chunk) <= _MAX_CHUNK_CHARS for chunk in result.chunks))

    def test_model_load_error_becomes_llm_error(self):
        fake_module = types.SimpleNamespace(
            SentenceTransformer=lambda _name, **_kwargs: (_ for _ in ()).throw(OSError("model missing"))
        )

        with patch.dict(sys.modules, {"sentence_transformers": fake_module}):
            with self.assertRaisesRegex(LLMError, "加载失败"):
                LocalEmbeddingAdapter("missing-model")._load()

    def test_local_embedding_load_never_uses_implicit_network(self):
        captured = {}

        class FakeModel:
            @staticmethod
            def get_sentence_embedding_dimension():
                return 512

        def build_model(name, **kwargs):
            captured["name"] = name
            captured.update(kwargs)
            return FakeModel()

        fake_module = types.SimpleNamespace(SentenceTransformer=build_model)
        with patch.dict(sys.modules, {"sentence_transformers": fake_module}):
            LocalEmbeddingAdapter("local-model")._load()

        self.assertEqual(captured["name"], "local-model")
        self.assertIs(captured["local_files_only"], True)

    def test_knowledge_upload_rejects_oversized_file_before_parsing(self):
        upload = _FakeUpload(b"a" * (1024 * 1024 + 1))

        with patch.object(knowledge.settings, "MAX_UPLOAD_MB", 1):
            with self.assertRaises(HTTPException) as context:
                asyncio.run(knowledge._extract_file_text(upload))

        self.assertEqual(context.exception.status_code, 413)

    def test_overwrite_preparation_failure_keeps_old_chunks(self):
        engine = create_engine("sqlite:///:memory:")
        KnowledgeChunk.__table__.create(engine)
        db = sessionmaker(bind=engine)()
        db.add(KnowledgeChunk(category="law", source="law.txt", content="旧条文", embedding=""))
        db.commit()
        chunks = [{"category": "law", "source": "law.txt", "content": "新条文"}]

        try:
            with patch.object(
                knowledge,
                "prepare_documents",
                side_effect=RuntimeError("preparation failed"),
            ):
                with self.assertRaisesRegex(RuntimeError, "preparation failed"):
                    knowledge._replace_source_chunks(db, "law.txt", chunks)

            contents = [row.content for row in db.query(KnowledgeChunk).all()]
            self.assertEqual(contents, ["旧条文"])
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
