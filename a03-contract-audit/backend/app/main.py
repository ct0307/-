"""FastAPI 应用入口。"""
import os

# Embedding 离线策略：禁止 huggingface 库在运行时联网验证模型文件。
# 模型已本地缓存（bge-small-zh-v1.5），联网验证只会超时拖慢首次请求。
# 必须在任何 transformers/sentence_transformers import 之前设置。
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.init_db import init_db

setup_logging(settings.DEBUG)
log = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    log.info("app.startup", env=settings.APP_ENV, llm_provider=settings.LLM_PROVIDER)
    yield
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
