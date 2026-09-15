"""应用配置：全部从环境变量/.env 读取，便于私有化部署与多环境切换。"""
import os
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

from app.core.url_security import safe_http_authority

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

    # 合同导入分类与草稿生命周期。
    CONTRACT_TYPE_CONFIRM_THRESHOLD: float = 0.60
    CONTRACT_TYPE_READY_THRESHOLD: float = 0.85
    CONTRACT_TRASH_RETENTION_DAYS: int = 30

    # OCR 资源门槛：防止超大扫描件耗尽 worker 内存或长期占用执行槽。
    OCR_MAX_PAGES: int = 100
    OCR_MAX_PAGE_PIXELS: int = 16_000_000
    OCR_DPI: int = 180
    OCR_TIMEOUT_SECONDS: float = 120.0
    OCR_MIN_CONFIDENCE: float = 0.75

    # 合同文件加密存储（企业数据安全硬约束）。
    # 留空则不加密（开发/演示期快速启动）；生产部署必须通过 .env 设置32字节Fernet密钥。
    # 生成命令：python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    FILE_ENCRYPT_KEY: str = ""

    # 数据库后端：postgres（生产/交付）| sqlite（本地无 Docker 时快速开发）
    DB_BACKEND: str = "sqlite"
    SQLITE_PATH: str = "storage/a03_dev.db"

    # LLM Adapter：当前项目测试基线使用 DeepSeek 中转；生产环境需评估合同出公网风险
    LLM_PROVIDER: str = "deepseek"  # qwen / deepseek / openclaw
    LLM_BASE_URL: str = "https://yorhamc.com/v1"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "deepseek-v4-flash"
    LLM_TIMEOUT: int = 120
    LLM_MAX_OUTPUT_TOKENS: int = 3200
    # 整体审查软时限必须短于任务 30 分钟租约，防止恢复任务与旧 worker 重叠。
    AUDIT_DEADLINE_SECONDS: int = Field(default=1500, gt=0, lt=1800)

    # Embedding 配置（RAG 向量化用）
    # EMBED_BACKEND=local（默认）：sentence-transformers 本地模型，合同数据不出企业
    # EMBED_BACKEND=api：走 LLM_BASE_URL + /embeddings 端点（需服务端支持 embedding）
    EMBED_BACKEND: str = "local"
    # 本地模型名（HuggingFace hub 或本地路径）。首次运行自动下载到 ~/.cache/huggingface
    # 推荐：BAAI/bge-small-zh-v1.5（中文检索专用，384维，~100MB）
    LOCAL_EMBED_MODEL: str = "BAAI/bge-small-zh-v1.5"
    # API 模式下的 embedding 模型名（EMBED_BACKEND=api 时生效）
    EMBED_MODEL: str = "quentinz/bge-large-zh-v1.5"
    # 向量维度（需与所用 embedding 模型一致）
    EMBED_DIM: int = 512  # bge-small-zh=512，bge-base-zh=768，bge-large-zh=1024

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        if self.APP_ENV != "prod":
            return self

        errors: list[str] = []
        if self.DEBUG:
            errors.append("DEBUG 必须为 false")
        if self.DB_BACKEND != "postgres":
            errors.append("DB_BACKEND 必须为 postgres")
        if not self.AUDIT_ASYNC:
            errors.append("AUDIT_ASYNC 必须为 true")
        if self.POSTGRES_PASSWORD == "a03pass" or len(self.POSTGRES_PASSWORD) < 12:
            errors.append("POSTGRES_PASSWORD 必须替换为至少 12 位的独立密钥")
        if self.JWT_SECRET == "CHANGE_ME_IN_PRODUCTION" or len(self.JWT_SECRET) < 32:
            errors.append("JWT_SECRET 必须替换为至少 32 位的独立密钥")
        try:
            Fernet(self.FILE_ENCRYPT_KEY.encode())
        except (TypeError, ValueError):
            errors.append("FILE_ENCRYPT_KEY 必须是有效的 Fernet 密钥")
        if errors:
            raise ValueError("生产配置不安全: " + "; ".join(errors))
        return self

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
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_HOST,
            port=self.POSTGRES_PORT,
            database=self.POSTGRES_DB,
        ).render_as_string(hide_password=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


def validate_llm_configuration(config: Settings) -> None:
    """校验模型连接的结构配置，不发起网络请求。"""
    errors: list[str] = []
    provider = config.LLM_PROVIDER.strip().lower()
    if provider not in {"qwen", "deepseek", "openclaw"}:
        errors.append("LLM_PROVIDER 不受支持")

    endpoint = config.LLM_BASE_URL.strip()
    try:
        parsed = urlsplit(endpoint)
        _ = parsed.port
    except ValueError:
        parsed = None
        errors.append("LLM_BASE_URL 端口无效")
    if parsed is None or parsed.scheme not in {"http", "https"} or not parsed.hostname:
        errors.append("LLM_BASE_URL 必须是有效的 HTTP(S) 地址")
    if not config.LLM_MODEL.strip():
        errors.append("LLM_MODEL 不能为空")
    if provider == "deepseek" and not config.LLM_API_KEY.strip():
        errors.append("DeepSeek 模式必须配置 LLM_API_KEY")

    if errors:
        raise ValueError("模型配置无效：" + "; ".join(errors))


def llm_configuration_metadata(config: Settings) -> dict[str, str]:
    """返回可安全记录的模型配置摘要。"""
    validate_llm_configuration(config)
    endpoint = safe_http_authority(config.LLM_BASE_URL.strip())
    if endpoint is None:
        raise ValueError("模型配置无效：LLM_BASE_URL 必须是有效的 HTTP(S) 地址")
    provider = config.LLM_PROVIDER.strip().lower()
    model = config.LLM_MODEL.strip()
    fingerprint = sha256(f"{provider}|{endpoint}|{model}".encode()).hexdigest()[:12]
    return {
        "llm_provider": provider,
        "llm_model": model,
        "llm_endpoint": endpoint,
        "llm_config_fingerprint": fingerprint,
    }
