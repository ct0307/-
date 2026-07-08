"""应用配置：全部从环境变量/.env 读取，便于私有化部署与多环境切换。"""
import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目 backend 目录（config.py 位于 backend/app/core/config.py，上溯 3 层）
BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 应用
    APP_NAME: str = "A03 企业合同合规审查系统"
    APP_ENV: str = "dev"  # dev / prod
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"

    # 数据库
    POSTGRES_USER: str = "a03"
    POSTGRES_PASSWORD: str = "a03pass"
    POSTGRES_DB: str = "a03_contract"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432

    # Redis / Celery
    REDIS_URL: str = "redis://localhost:6379/0"
    # 审查是否走异步队列。生产开 True（需 Redis+worker）；本地无 Redis 时 False 同步执行。
    AUDIT_ASYNC: bool = False

    # 安全（生产环境必须通过 .env 覆盖）
    JWT_SECRET: str = "CHANGE_ME_IN_PRODUCTION"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480

    # 文件存储（私有化本地存储）。相对路径按 backend 目录解析，避免依赖启动工作目录。
    STORAGE_DIR: str = "storage"
    MAX_UPLOAD_MB: int = 50

    # 合同文件加密存储（企业数据安全硬约束）。
    # 留空则不加密（开发/演示期快速启动）；生产部署必须通过 .env 设置32字节Fernet密钥。
    # 生成命令：python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    FILE_ENCRYPT_KEY: str = ""

    # 数据库后端：postgres（生产/交付）| sqlite（本地无 Docker 时快速开发）
    DB_BACKEND: str = "sqlite"
    SQLITE_PATH: str = "storage/a03_dev.db"

    # LLM Adapter：默认对接私有化模型，避免合同数据出公网
    LLM_PROVIDER: str = "qwen"  # qwen / deepseek / openclaw
    LLM_BASE_URL: str = "http://localhost:11434/v1"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "qwen2.5:14b"
    LLM_TIMEOUT: int = 120
    # Embedding 模型与维度（RAG 向量化用）。维度须与所选 embedding 模型一致。
    EMBED_MODEL: str = "quentinz/bge-large-zh-v1.5"  # 常用中文 embedding，Ollama 可拉
    EMBED_DIM: int = 1024

    def _abs(self, p: str) -> str:
        """相对路径按 BASE_DIR 解析为绝对路径；已是绝对路径则原样返回。"""
        return p if os.path.isabs(p) else str(BASE_DIR / p)

    @property
    def storage_path(self) -> str:
        return self._abs(self.STORAGE_DIR)

    @property
    def sqlite_abs_path(self) -> str:
        return self._abs(self.SQLITE_PATH)

    @property
    def database_url(self) -> str:
        if self.DB_BACKEND == "sqlite":
            return f"sqlite:///{self.sqlite_abs_path}"
        return (
            f"postgresql+psycopg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
