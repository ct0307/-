"""建表初始化。

SQLite 开发期直接 create_all；PostgreSQL 交付期改走 alembic 迁移。
"""
import os

from sqlalchemy import inspect, text

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import hash_password
from app.db.session import Base, SessionLocal, engine

# 导入模型以注册到 Base.metadata（必须，否则 create_all 建不出表）
from app.models import models  # noqa: F401
from app.models.models import User

log = get_logger("db")

# 开发期种子账号（生产环境应通过管理后台创建，密码从 env 或首启向导设置）
_SEED_USERS = [
    {"username": "admin", "password": "admin123", "role": "admin", "department": "管理"},
    {"username": "legal", "password": "legal123", "role": "legal", "department": "法务部"},
]


def init_db() -> None:
    # 确保存储目录存在（SQLite 文件与合同文件都放这里）
    os.makedirs(settings.storage_path, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    _migrate_dev_columns()
    _seed_users()
    log.info("db.init", backend=settings.DB_BACKEND, tables=list(Base.metadata.tables.keys()))


# 开发期轻量补列：create_all 只建表不改已有表结构。SQLite 无 alembic 时，
# 检测到 risks 缺少新增列则 ADD COLUMN，避免删库。生产（PostgreSQL）走 alembic 迁移。
_DEV_COLUMNS = {
    "risks": [("tier", "VARCHAR(8) DEFAULT 'yellow'")],
}


def _migrate_dev_columns() -> None:
    if settings.DB_BACKEND != "sqlite":
        return
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table, columns in _DEV_COLUMNS.items():
            if not inspector.has_table(table):
                continue
            existing = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl in columns:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                    log.info("db.migrate_column", table=table, column=name)


def _seed_users() -> None:
    db = SessionLocal()
    try:
        for u in _SEED_USERS:
            if not db.query(User).filter(User.username == u["username"]).first():
                db.add(User(
                    username=u["username"],
                    password_hash=hash_password(u["password"]),
                    role=u["role"],
                    department=u["department"],
                ))
        db.commit()
    finally:
        db.close()
