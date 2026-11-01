"""仅挂载认证路由，使用内存数据库验证密码输入边界。"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.v1.endpoints import auth
from app.core.security import hash_password
from app.db.session import Base, get_db
from app.models.models import User


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(User(username="test_user", password_hash=hash_password("a" * 72), role="legal"))
        db.add(User(username="chinese_user", password_hash=hash_password("密" * 24), role="legal"))
        db.commit()

    def test_db():
        with Session(engine) as db:
            yield db

    app = FastAPI()
    app.include_router(auth.router, prefix="/auth")
    app.dependency_overrides[get_db] = test_db
    with TestClient(app) as test_client:
        yield test_client
    engine.dispose()


@pytest.mark.parametrize("password", ["a" * 72 + "first", "a" * 72 + "second", "密" * 25])
def test_login_rejects_oversize_password_with_clear_message(client, password):
    response = client.post("/auth/login", data={"username": "test_user", "password": password})

    assert response.status_code == 422
    assert "72" in response.json()["detail"]
    assert "字节" in response.json()["detail"]
    assert password not in response.text


@pytest.mark.parametrize(("username", "password"), [("test_user", "a" * 72), ("chinese_user", "密" * 24)])
def test_login_accepts_exact_72_utf8_bytes(client, username, password):
    response = client.post("/auth/login", data={"username": username, "password": password})

    assert response.status_code == 200
    assert response.json()["access_token"]


def test_invalid_short_password_keeps_unauthorized_response(client):
    response = client.post("/auth/login", data={"username": "test_user", "password": "wrong"})

    assert response.status_code == 401
    assert response.json()["detail"] == "用户名或密码错误"
