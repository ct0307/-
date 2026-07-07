"""数据库会话与 ORM 基类。"""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session

from app.core.config import settings

# SQLite 在多线程下需关闭 same-thread 检查；PostgreSQL 不需要。
_connect_args = {"check_same_thread": False} if settings.DB_BACKEND == "sqlite" else {}
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    echo=settings.DEBUG,
    connect_args=_connect_args,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：请求级数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
