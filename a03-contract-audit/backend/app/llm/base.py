"""LLM Adapter 抽象基类。

企业核心资产：统一封装不同模型提供方（私有化 Qwen/DeepSeek、OpenClaw），
上层业务（审查、要素抽取）只依赖此接口，切换模型不改业务代码。
默认对接私有化部署，避免合同数据出公网。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


class LLMError(RuntimeError):
    """LLM 调用失败：网络/超时/协议错误统一包成此异常，上层可捕获降级。"""


@dataclass
class LLMResponse:
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0  # 用于 OpenClaw vs 通用模型的算力对比记录
    finish_reason: str | None = None


class LLMAdapter(ABC):
    """所有模型适配器的统一接口。"""

    @abstractmethod
    def chat(self, system: str, user: str, *, temperature: float = 0.2) -> LLMResponse:
        """单轮对话，返回文本结果。"""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """文本向量化，供 RAG 检索使用。"""
