"""风险追问接口：用户针对某条风险条款向 AI 追问细节。

绑定风险上下文（category/original_text/basis/suggestion/confidence）作为 system prompt，
保证 AI 回复聚焦于当前条款而非泛泛作答。
对话历史由前端维护并随每次请求一起传入，后端无状态。
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.core.logging import get_logger
from app.llm.factory import get_llm_adapter
from app.models.models import LLMCallLog, User

log = get_logger("chat")

router = APIRouter()


# —— 请求 / 响应模型 ——

class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class RiskContext(BaseModel):
    category: str
    original_text: str = ""
    basis: str = ""
    suggestion: str = ""
    confidence: int = 0


class ChatRequest(BaseModel):
    risk_context: RiskContext
    message: str = Field(..., min_length=1, max_length=1000)
    history: list[HistoryMessage] = Field(default_factory=list, max_length=20)


class ChatResponse(BaseModel):
    reply: str
    model: str


# —— 系统 Prompt 构造 ——

def _build_system_prompt(ctx: RiskContext) -> str:
    parts = [
        "你是企业合规法律助手。用户正在审阅合同时发现了一条风险条款，请基于以下检测结果回答用户的追问。",
        "",
        f"【风险类别】{ctx.category}",
    ]
    if ctx.original_text:
        parts.append(f"【命中原文】{ctx.original_text[:400]}")
    if ctx.basis:
        parts.append(f"【法规依据】{ctx.basis}")
    if ctx.suggestion:
        parts.append(f"【系统建议】{ctx.suggestion}")
    if ctx.confidence:
        parts.append(f"【置信度】{ctx.confidence}%")
    parts += [
        "",
        "回答要求：",
        "1. 结合上述背景作答，不要脱离当前条款泛泛而谈",
        "2. 语言简洁，300 字以内",
        "3. 涉及具体法律建议时注明「仅供参考，以人工复核为准」",
    ]
    return "\n".join(parts)


def _build_user_prompt(history: list[HistoryMessage], message: str) -> str:
    """将历史对话和当前消息拼成单轮 user 文本（兼容 chat(system, user) 接口）。"""
    if not history:
        return message
    lines = []
    for m in history[-6:]:  # 最多带 6 条历史，避免 token 过多
        prefix = "用户：" if m.role == "user" else "助手："
        lines.append(f"{prefix}{m.content}")
    lines.append(f"用户：{message}")
    return "\n\n".join(lines)


# —— 端点 ——

@router.post("", response_model=ChatResponse)
def chat_with_risk(
    req: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """针对风险条款的追问对话（所有已登录角色可用）。"""
    llm = get_llm_adapter()
    system = _build_system_prompt(req.risk_context)
    user_text = _build_user_prompt(req.history, req.message)

    try:
        resp = llm.chat(system, user_text, temperature=0.4)
    except Exception as exc:
        log.warning("chat.llm_failed", error=str(exc)[:200])
        raise HTTPException(status_code=503, detail="AI 服务暂时不可用，请稍后重试")

    # 记录调用日志（非阻断性）
    try:
        db.add(LLMCallLog(
            contract_id=None,
            agent="chat",
            provider=settings.LLM_PROVIDER,
            model=resp.model,
            prompt_tokens=resp.prompt_tokens,
            completion_tokens=resp.completion_tokens,
            latency_ms=resp.latency_ms,
            mode="chat",
        ))
        db.commit()
    except Exception as exc:
        log.warning("chat.log_failed", error=str(exc)[:120])

    return ChatResponse(reply=resp.text, model=resp.model)
