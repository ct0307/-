"""复核正文读取：完整文本、缓存有效性和授权边界。"""
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user
from app.api.v1.router import api_router
from app.db.session import Base, get_db
from app.models.models import Contract, User
from app.services.parser.cache import save_parse_cache
from app.services.parser.extractor import DocumentParseResult


@pytest.fixture
def document_client(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "FILE_ENCRYPT_KEY", "")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(username="reader", password_hash="unused", role="legal", department="法务部")
        db.add(user)
        db.flush()
        contract = Contract(filename="合成合同.txt", storage_path="/private/never-expose.txt",
                            uploaded_by=user.id, department="法务部", status="parsed",
                            content_sha256="a" * 64)
        db.add(contract)
        db.commit()
        app = FastAPI()
        app.include_router(api_router, prefix="/api/v1")
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: user
        with TestClient(app) as client:
            yield client, db, user, contract
    engine.dispose()


def test_reader_returns_entire_cached_text_and_parse_quality(document_client):
    client, db, _, contract = document_client
    text = "第一条 正常背景条款。\n第二条 验收后十日付款。\n附件 完整交付清单。"
    save_parse_cache(db, contract, DocumentParseResult(text=text, source="mixed", requires_review=True,
                                                    review_reason="存在缺页", total_pages=3, missing_pages=(2,)))
    db.commit()
    response = client.get(f"/api/v1/contracts/{contract.id}/document")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["text"] == text
    assert data["status"] == "available"
    assert data["requires_review"] is True and data["missing_pages"] == [2]
    assert "storage_path" not in data and "/private/" not in response.text


@pytest.mark.parametrize("state", ["missing", "stale", "empty"])
def test_reader_distinguishes_unavailable_and_empty_text(document_client, state):
    client, db, _, contract = document_client
    if state != "missing":
        save_parse_cache(db, contract, DocumentParseResult(text="" if state == "empty" else "旧版本正文", source="native"))
        if state == "stale":
            contract.content_sha256 = "b" * 64
        db.commit()
    response = client.get(f"/api/v1/contracts/{contract.id}/document")
    assert response.status_code == 200
    data = response.json()
    assert data["text"] == ""
    assert data["status"] == ("empty" if state == "empty" else "unavailable")
    assert data["message"]


@pytest.mark.parametrize("role,department,expected", [("business", "法务部", 403), ("legal", "采购部", 403),
                                                     ("finance", "法务部", 200), ("admin", "其他部门", 200)])
def test_reader_enforces_role_and_department(document_client, role, department, expected):
    client, db, user, contract = document_client
    user.role, user.department = role, department
    db.commit()
    assert client.get(f"/api/v1/contracts/{contract.id}/document").status_code == expected


def test_reader_hides_deleted_or_unknown_contract(document_client):
    client, db, _, contract = document_client
    contract.deleted_at = datetime.now(timezone.utc)
    db.commit()
    assert client.get(f"/api/v1/contracts/{contract.id}/document").status_code == 404
    assert client.get("/api/v1/contracts/999999/document").status_code == 404
