"""Pydantic 请求/响应模型。骨架：仅示例核心结构。"""
from datetime import datetime

from pydantic import BaseModel


class RiskOut(BaseModel):
    id: int
    agent: str
    level: str
    category: str
    original_text: str
    basis: str
    suggestion: str
    confidence: int
    tier: str  # 人工干预档位：green/yellow/red
    review_status: str

    model_config = {"from_attributes": True}


class CrossCheckOut(BaseModel):
    """交叉验证 / 冲突消解项：跨 Agent 触发的复查结果（审查态动态结果，不落库）。"""
    id: str
    from_agent: str
    to_agent: str
    trigger: str
    action: str
    verdict: str  # conflict/watch/confirmed
    note: str
    category: str


class AuditResponse(BaseModel):
    """审查触发响应：同步返回风险数与冲突项；异步返回 task_id。"""
    contract_id: int
    status: str
    risk_count: int | None = None
    cross_checks: list[CrossCheckOut] = []
    task_id: str | None = None


class ContractOut(BaseModel):
    id: int
    filename: str
    contract_type: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class RiskStatusUpdate(BaseModel):
    review_status: str  # confirmed/ignored/to_modify


class KnowledgeImport(BaseModel):
    """知识库导入：一段法规/规则/模板文本，服务端切片后向量化入库。"""
    category: str = "rule"      # law/rule/template
    source: str = ""            # 来源（法规名/文件名）
    content: str                # 正文，服务端按段落切片
