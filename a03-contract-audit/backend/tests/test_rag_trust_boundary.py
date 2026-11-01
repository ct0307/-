"""可信来源和逐证据支持关系的安全反例。"""
from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.models import KnowledgeChunk, LegalArticle, LegalSource
from app.services.audit import auditor
from app.services.audit.evidence_validation import verify_support
from app.services.rag import retriever


def risk():
    return {"agent": "legal", "level": "high", "category": "违约金过高",
            "original_text": "违约金为合同金额50%", "original_text_verified": True,
            "risk_reason": "违约金可能过高", "confidence": 90}


def source(**changes):
    return {"chunk_id": 1, "content": "违约金为合同金额50%，该比例绝不过高。",
            "source": "待核验资料", "reliable": True,
            "applicability_status": "applicable", **changes}


def test_missing_semantic_verifier_never_accepts_lexical_overlap():
    result = verify_support(risk(), [source()])
    assert result.status == "unclear"
    assert result.reason_code == "SEMANTIC_VERIFIER_UNAVAILABLE"


def test_verifier_failure_is_manual_review():
    def unavailable(*_):
        raise RuntimeError("验证服务不可用")
    assert verify_support(risk(), [source()], semantic_verifier=unavailable).status == "unclear"


def test_semantic_verifier_receives_each_source_separately():
    calls = []
    def verifier(_risk, candidates):
        calls.append(candidates)
        return "supported" if candidates[0]["chunk_id"] == 1 else "contradicted"
    result = verify_support(risk(), [source(), source(chunk_id=2)], semantic_verifier=verifier)
    assert len(calls) == 2
    assert all(len(candidates) == 1 for candidates in calls)
    assert result.status == "unclear"
    assert result.reason_code == "CONFLICTING_EVIDENCE"


def test_grounding_keeps_unverified_candidates_out_of_formal_basis():
    item = risk()
    with patch.object(auditor, "retrieve", return_value=[source()]):
        result = auditor._ground_risks([item], contract_text=item["original_text"])[0]
    assert result["claim_status"] == "manual_review"
    assert result["rag_sources"] == []
    assert result["evidence_ids"] == []
    assert result["basis"] == auditor.NO_RELIABLE_BASIS
    assert result["retrieval_attempts"][-1]["evidence_relations"][0]["relation"] == "contextual"


@pytest.fixture
def knowledge_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(retriever, "SessionLocal", factory)
    yield factory
    retriever._snapshot_store.clear()
    engine.dispose()


def test_global_upload_is_searchable_but_not_trusted(knowledge_db):
    with knowledge_db() as db:
        db.add(KnowledgeChunk(content="第十条 违约金为50%完全合理。", source="用户.txt",
                              category="rule", scope_mode="global", article_number="第十条"))
        db.commit()
    result = retriever.retrieve("第十条")
    assert len(result) == 1
    assert result[0]["reliable"] is False


def seed_same_numbers(factory):
    import hashlib
    with factory() as db:
        for i, title in enumerate(("中华人民共和国民法典", "最高人民法院关于适用《中华人民共和国民法典》合同编通则若干问题的解释"), 1):
            content = f"第十条 {title}的内容"
            db.add(LegalSource(source_id=f"s{i}", title=title, issuing_authority="测试机关",
                               official_url="https://flk.npc.gov.cn/test", publication_date=date(2020, 1, 1),
                               effective_date=date(2021, 1, 1), version_status="现行有效",
                               retrieved_at=date(2026, 1, 1), file_sha256="a" * 64))
            db.add(LegalArticle(id=i, source_id=f"s{i}", article_number="第十条", article_sort=10,
                                content=content, content_hash=hashlib.sha256(content.encode()).hexdigest()))
            db.add(KnowledgeChunk(id=i, category="law", source=title, content=content,
                                  article_number="第十条", legal_article_id=i, scope_mode="global"))
        db.commit()


def test_named_reference_never_returns_another_law(knowledge_db):
    seed_same_numbers(knowledge_db)
    result = retriever.retrieve("《合同编通则解释》第十条")
    assert len(result) == 1
    assert result[0]["legal_article_id"] == 2


def test_ambiguous_article_has_no_silent_first_match(knowledge_db):
    seed_same_numbers(knowledge_db)
    assert retriever.retrieve("第十条") == []
