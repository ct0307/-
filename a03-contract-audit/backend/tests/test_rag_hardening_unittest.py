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
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.api.v1.endpoints import knowledge
from app.api.v1.endpoints.knowledge import _MAX_CHUNK_CHARS, _smart_split
from app.llm.base import LLMError
from app.llm.adapters.local_embedding import LocalEmbeddingAdapter
from app.models.models import KnowledgeChunk
from app.services.rag import retriever


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
        self.assertTrue(all("民法典" not in item["source"] for item in results))

    def test_article_number_is_extracted_from_chunk_content(self):
        content = "【第三编 合同】\n第五百八十五条 当事人可以约定违约金。"

        self.assertEqual(retriever._extract_article_number(content), "第五百八十五条")

    def test_alembic_history_loads_rag_metadata_revision(self):
        backend_dir = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", "history"],
            cwd=backend_dir,
            capture_output=True,
            text=True,
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
                [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
                cwd=backend_dir,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(upgrade.returncode, 0, upgrade.stdout + upgrade.stderr)

            engine = create_engine(f"sqlite:///{database.as_posix()}")
            migrated_tables = set(inspect(engine).get_table_names()) - {"alembic_version"}
            self.assertEqual(migrated_tables, set(KnowledgeChunk.metadata.tables))
            engine.dispose()

            downgrade = subprocess.run(
                [sys.executable, "-m", "alembic", "-c", "alembic.ini", "downgrade", "base"],
                cwd=backend_dir,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(downgrade.returncode, 0, downgrade.stdout + downgrade.stderr)

            engine = create_engine(f"sqlite:///{database.as_posix()}")
            remaining_tables = set(inspect(engine).get_table_names()) - {"alembic_version"}
            self.assertEqual(remaining_tables, set())
            engine.dispose()

    def test_filter_docs_applies_contract_dimension_category_and_date(self):
        docs = [
            (
                1, "采购付款规则", "采购制度", "", "rule", "第一条", "2026",
                date(2026, 1, 1), None, '["采购合同"]', '["payment"]', None, None,
            ),
            (
                2, "劳动争议规则", "劳动制度", "", "rule", "第二条", "2026",
                date(2026, 1, 1), None, '["劳动合同"]', '["legal"]', None, None,
            ),
            (
                3, "已失效采购规则", "旧制度", "", "rule", "第三条", "2020",
                date(2020, 1, 1), date(2025, 12, 31), '["采购合同"]', '["payment"]', None, None,
            ),
            (
                4, "无范围限制法规", "通用法规", "", "law", "第四条", None,
                None, None, "[]", "[]", None, None,
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
