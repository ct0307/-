"""LLM Adapter 工厂：按配置返回适配器实例，业务层通过此处获取模型。

chat 与 embedding 分开获取，互不影响：
- get_llm_adapter()       → chat 用（DeepSeek/Qwen/OpenClaw）
- get_embedding_adapter() → embedding 用，默认本地 sentence-transformers
  合同数据不出企业（企业安全要求），本地模型离线可用。
"""
from functools import lru_cache

from app.core.config import settings
from app.llm.adapters.openai_compatible import OpenAICompatibleAdapter
from app.llm.base import LLMAdapter


def get_llm_adapter() -> LLMAdapter:
    """返回 chat 用的 LLM 适配器（DeepSeek / Qwen / OpenClaw）。"""
    provider = settings.LLM_PROVIDER.lower()
    if provider in {"qwen", "deepseek", "openclaw"}:
        return OpenAICompatibleAdapter()
    raise ValueError(f"未知 LLM_PROVIDER: {provider}")


@lru_cache(maxsize=1)
def _local_embed_singleton() -> LLMAdapter:
    """本地 embedding 适配器单例（模型加载一次，后续复用）。"""
    from app.llm.adapters.local_embedding import LocalEmbeddingAdapter
    return LocalEmbeddingAdapter(settings.LOCAL_EMBED_MODEL)


def get_embedding_adapter() -> LLMAdapter:
    """返回 embedding 专用适配器。

    EMBED_BACKEND=local（默认）→ sentence-transformers 本地模型，合同数据不出企业
    EMBED_BACKEND=api           → OpenAI 兼容 /embeddings 端点（需服务端支持）
    """
    backend = settings.EMBED_BACKEND.lower()
    if backend == "local":
        return _local_embed_singleton()
    if backend == "api":
        return OpenAICompatibleAdapter()
    raise ValueError(f"未知 EMBED_BACKEND: {backend}")
