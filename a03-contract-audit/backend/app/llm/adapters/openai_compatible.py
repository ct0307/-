"""OpenAI 兼容协议适配器。

覆盖大多数私有化部署方式：Ollama、vLLM、DeepSeek/Qwen 官方 API、
以及多数以 OpenAI 协议暴露的自建推理服务。OpenClaw 若提供兼容端点亦可复用。

用 httpx 手写调用，不引入 openai SDK：零新增依赖，且对非标私有化端点更可控。
所有调用记录 latency_ms 与 token 用量，供 OpenClaw 与通用模型的算力对比。
"""
import time

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.llm.base import LLMAdapter, LLMError, LLMResponse

log = get_logger("llm")


class OpenAICompatibleAdapter(LLMAdapter):
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
        embed_model: str | None = None,
        max_output_tokens: int | None = None,
    ) -> None:
        # base_url 末尾去斜杠，拼接端点时统一加前缀
        self.base_url = (base_url or settings.LLM_BASE_URL).rstrip("/")
        self.api_key = api_key or settings.LLM_API_KEY
        self.model = model or settings.LLM_MODEL
        # embedding 用独立模型（EMBED_MODEL），与 chat 模型解耦
        self.embed_model = embed_model or settings.EMBED_MODEL
        self.timeout = timeout or settings.LLM_TIMEOUT
        self.max_output_tokens = (
            settings.LLM_MAX_OUTPUT_TOKENS
            if max_output_tokens is None
            else max_output_tokens
        )
        if self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens 必须大于 0")

    def _headers(self) -> dict[str, str]:
        # 本地 Ollama 等无需鉴权；有 key 才带 Authorization，避免空 Bearer 被拒。
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _post(self, path: str, payload: dict) -> tuple[dict, int]:
        """POST 并返回 (响应 JSON, 耗时毫秒)。异常统一包成 LLMError。"""
        url = f"{self.base_url}{path}"
        start = time.perf_counter()
        try:
            resp = httpx.post(url, json=payload, headers=self._headers(), timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except httpx.TimeoutException as exc:
            log.error("llm.timeout", path=path, timeout=self.timeout)
            raise LLMError(f"LLM 调用超时（{self.timeout}s）：{path}") from exc
        except httpx.HTTPStatusError as exc:
            request_id = (
                exc.response.headers.get("x-ds-trace-id")
                or exc.response.headers.get("x-request-id")
                or ""
            )
            log.error(
                "llm.http_error",
                path=path,
                status=exc.response.status_code,
                request_id=request_id,
            )
            raise LLMError(f"LLM 返回错误状态 {exc.response.status_code}：{path}") from exc
        except httpx.HTTPError as exc:
            log.error(
                "llm.request_error",
                path=path,
                exception_type=type(exc).__name__,
            )
            raise LLMError(f"LLM 请求失败：{path}") from exc
        latency_ms = int((time.perf_counter() - start) * 1000)
        return data, latency_ms

    def chat(self, system: str, user: str, *, temperature: float = 0.2) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": self.max_output_tokens,
            "stream": False,
        }
        data, latency_ms = self._post("/chat/completions", payload)
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            log.error("llm.bad_response", keys=list(data.keys()) if isinstance(data, dict) else type(data).__name__)
            raise LLMError("LLM 响应结构异常：未找到 choices[0].message.content") from exc
        usage = data.get("usage", {}) if isinstance(data, dict) else {}
        log.info(
            "llm.chat",
            model=self.model,
            latency_ms=latency_ms,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )
        return LLMResponse(
            text=text,
            model=data.get("model", self.model),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            latency_ms=latency_ms,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = {"model": self.embed_model, "input": texts}
        data, latency_ms = self._post("/embeddings", payload)
        try:
            # OpenAI 协议不保证返回顺序，按 index 排序后取 embedding
            items = sorted(data["data"], key=lambda x: x["index"])
            vectors = [item["embedding"] for item in items]
        except (KeyError, TypeError) as exc:
            log.error("llm.bad_embed_response")
            raise LLMError("LLM 向量响应结构异常：未找到 data[].embedding") from exc
        log.info("llm.embed", model=self.embed_model, count=len(vectors), latency_ms=latency_ms)
        return vectors
