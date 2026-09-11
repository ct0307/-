"""FastAPI 应用入口。"""
import os

# Embedding 离线策略：禁止 huggingface 库在运行时联网验证模型文件。
# 模型已本地缓存（bge-small-zh-v1.5），联网验证只会超时拖慢首次请求。
# 必须在任何 transformers/sentence_transformers import 之前设置。
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1.router import api_router
from app.core.config import settings, validate_llm_configuration
from app.core.logging import get_logger, setup_logging
from app.db.init_db import init_db
from app.db.session import engine
from app.api.v1.endpoints.runtime import _get_cached_runtime_status

setup_logging(settings.DEBUG)
log = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_llm_configuration(settings)
    init_db()
    if settings.AUDIT_ASYNC:
        from app.tasks.audit_tasks import recover_orphaned_batch_items

        recovered = recover_orphaned_batch_items()
        log.info("audit_recovery.backend_startup", recovered=recovered)
    else:
        from app.tasks.dispatcher import recover_local_audit_items

        recovered = recover_local_audit_items()
        log.info("audit_recovery.local_startup", recovered=recovered)
    log.info("app.startup", env=settings.APP_ENV, llm_provider=settings.LLM_PROVIDER)
    yield
    if not settings.AUDIT_ASYNC:
        from app.tasks.dispatcher import shutdown_local_dispatcher

        shutdown_local_dispatcher()
    log.info("app.shutdown")


app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG, lifespan=lifespan)

# 开发期放开 CORS，生产由 .env / 网关收紧
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/health", tags=["系统"])
def health() -> dict:
    return {"status": "ok", "app": settings.APP_NAME}


@app.get("/health/live", tags=["系统"])
def health_live() -> dict:
    return {"status": "ok", "app": settings.APP_NAME}


def collect_readiness() -> dict[str, dict[str, object]]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        database = {"ready": True}
    except Exception:
        database = {"ready": False, "error_code": "database_unavailable"}

    try:
        validate_llm_configuration(settings)
        runtime = _get_cached_runtime_status(force_refresh=True)
        model = {"ready": runtime.status == "online"}
        if runtime.status != "online":
            model["error_code"] = runtime.error_code or "probe_failed"
    except ValueError:
        model = {"ready": False, "error_code": "invalid_configuration"}
    except Exception:
        model = {"ready": False, "error_code": "probe_failed"}
    return {"database": database, "model": model}


@app.get("/health/ready", tags=["系统"])
def health_ready(response: Response) -> dict:
    checks = collect_readiness()
    ready = all(bool(check.get("ready")) for check in checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if ready else "not_ready", "checks": checks}
