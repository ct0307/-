"""v1 路由聚合。"""
from fastapi import APIRouter

from app.api.v1.endpoints import (
    admin, auth, chat, contracts, dashboard, knowledge,
    rectifications, risks, reports, rules,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["认证"])
api_router.include_router(contracts.router, prefix="/contracts", tags=["合同"])
api_router.include_router(risks.router, prefix="/risks", tags=["风险"])
api_router.include_router(reports.router, prefix="/reports", tags=["报表"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["看板"])
api_router.include_router(knowledge.router, prefix="/knowledge", tags=["知识库"])
api_router.include_router(rectifications.router, prefix="/rectifications", tags=["整改跟踪"])
api_router.include_router(rules.router, prefix="", tags=["规则与模板"])
api_router.include_router(admin.router, prefix="/admin", tags=["权限与审计"])
api_router.include_router(chat.router, prefix="/chat", tags=["追问"])
