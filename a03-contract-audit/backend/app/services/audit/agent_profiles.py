"""法务与财务 Agent 的稳定职责配置。"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal


AgentRole = Literal["legal", "finance"]


@dataclass(frozen=True)
class AgentProfile:
    role: AgentRole
    name: str
    focus: str
    topics: tuple[str, ...]


AGENT_PROFILES = MappingProxyType({
    "legal": AgentProfile(
        role="legal",
        name="法务专家 Agent",
        focus="违约责任、争议解决、知识产权归属、保密条款、验收标准、合同主体资格、关联交易识别",
        topics=(
            "违约 违约责任 违约金",
            "争议 仲裁 诉讼 管辖",
            "知识产权 著作权 保密",
            "合同主体 甲方 乙方 关联交易",
        ),
    ),
    "finance": AgentProfile(
        role="finance",
        name="财务会计 Agent",
        focus="合同金额、付款节点、发票绑定、违约金上限、币种与大小写一致性、预算合规、收款账户与价格公允性",
        topics=(
            "金额 价款 币种",
            "付款 发票 结算",
            "违约金 上限 赔偿",
            "期限 履约 现金流",
        ),
    ),
})

AGENT_ORDER: tuple[AgentRole, ...] = ("legal", "finance")

DIMENSION_TOPICS = MappingProxyType({
    "legal": "合同主体 合同效力 权利义务",
    "risk": "权责失衡 合规风险",
    "payment": "金额 付款 发票 结算",
    "breach": "违约责任 违约金 赔偿",
    "ip": "知识产权 著作权",
    "confidentiality": "保密 数据安全",
    "termination": "终止 解除 履约期限",
    "dispute": "争议 仲裁 诉讼 管辖",
})

ROLE_DIMENSIONS = MappingProxyType({
    "legal": frozenset({
        "legal", "risk", "breach", "ip", "confidentiality", "termination", "dispute",
    }),
    "finance": frozenset({"risk", "payment", "breach", "termination"}),
})


def agent_profile(role: str) -> AgentProfile:
    try:
        return AGENT_PROFILES[role]
    except KeyError as exc:
        raise ValueError(f"未知 Agent 角色: {role}") from exc
