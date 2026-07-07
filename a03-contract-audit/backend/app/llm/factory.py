"""LLM Adapter 工厂：按配置返回适配器实例，业务层通过此处获取模型。"""
from app.core.config import settings
from app.llm.adapters.openai_compatible import OpenAICompatibleAdapter
from app.llm.base import LLMAdapter


def get_llm_adapter() -> LLMAdapter:
    provider = settings.LLM_PROVIDER.lower()
    # qwen / deepseek / openclaw 目前均可走 OpenAI 兼容协议；
    # 若 OpenClaw 有专有协议，此处新增分支并实现独立 adapter。
    if provider in {"qwen", "deepseek", "openclaw"}:
        return OpenAICompatibleAdapter()
    raise ValueError(f"未知 LLM_PROVIDER: {provider}")
