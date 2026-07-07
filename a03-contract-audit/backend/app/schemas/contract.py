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
    review_status: str

    model_config = {"from_attributes": True}


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
