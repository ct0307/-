"""LLM Adapter 抽象基类。

企业核心资产：统一封装不同模型提供方（私有化 Qwen/DeepSeek、OpenClaw），
上层业务（审查、要素抽取）只依赖此接口，切换模型不改业务代码。
默认对接私有化部署，避免合同数据出公网。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from types import GeneratorType
from typing import Literal


class _ImmutableResponseFormat(dict[str, str]):
    def __new__(cls, source=(), /, **kwargs):
        if isinstance(source, GeneratorType):
            return dict(source, **kwargs)
        return super().__new__(cls)

    def __init__(self, *_args, **_kwargs):
        self._immutable()

    @classmethod
    def _from_dict(cls, values: dict[str, str]):
        instance = dict.__new__(cls)
        for key, value in values.items():
            dict.__setitem__(instance, key, value)
        return instance

    def __copy__(self):
        return type(self)._from_dict(dict(self))

    def __deepcopy__(self, memo):
        return type(self)._from_dict(dict(self))

    def __reduce__(self):
        return _restore_immutable_response_format, (dict(self),)

    @staticmethod
    def _immutable(*_args, **_kwargs):
        raise TypeError("response_format is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


def _restore_immutable_response_format(values: dict[str, str]) -> _ImmutableResponseFormat:
    return _ImmutableResponseFormat._from_dict(values)


@dataclass(frozen=True)
class ChatOptions:
    max_output_tokens: int | None = None
    response_format: dict[str, str] | None = None
    request_id: str | None = None
    thinking: Literal["enabled", "disabled"] | None = None

    def __post_init__(self) -> None:
        if self.response_format is not None:
            if not isinstance(self.response_format, dict):
                raise TypeError("response_format must be a dict")
            object.__setattr__(
                self,
                "response_format",
                _ImmutableResponseFormat._from_dict(self.response_format),
            )


class LLMError(RuntimeError):
    """LLM 调用失败：网络/超时/协议错误统一包成此异常，上层可捕获降级。"""

    def __init__(
        self,
        message: str,
        code: str = "MODEL_UNAVAILABLE",
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


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
    def chat(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.2,
        options: ChatOptions | None = None,
    ) -> LLMResponse:
        """单轮对话，返回文本结果。"""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """文本向量化，供 RAG 检索使用。"""
