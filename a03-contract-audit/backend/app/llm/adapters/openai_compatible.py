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
from app.llm.base import ChatOptions, LLMAdapter, LLMError, LLMResponse

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

    def _headers(self, request_id: str | None = None) -> dict[str, str]:
        # 本地 Ollama 等无需鉴权；有 key 才带 Authorization，避免空 Bearer 被拒。
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if request_id:
            headers["X-Request-ID"] = request_id
        return headers

    def _post(
        self,
        path: str,
        payload: dict,
        *,
        request_id: str | None = None,
    ) -> tuple[dict, int]:
        """POST 并返回 (响应 JSON, 耗时毫秒)。异常统一包成 LLMError。"""
        from app.core.model_policy import check_model_endpoint
        if settings.MODEL_PROCESSING_MODE == "rules_fallback":
            raise LLMError(
                "当前配置已禁用模型，请联系管理员启用模型后重新审查",
                code="MODEL_DISABLED", retryable=False,
            )
        try:
            check_model_endpoint(self.base_url, settings)
            if settings.MODEL_PROCESSING_MODE == 'external_model':
                from app.services.sensitive_data import contains_sensitive_data
                if contains_sensitive_data(payload):
                    raise ValueError('检测到已知敏感字段，禁止发送至外部模型；请使用私有模型或人工复核')
        except ValueError as exc:
            raise LLMError(str(exc), code="MODEL_OUTBOUND_BLOCKED", retryable=False) from exc
        url = f"{self.base_url}{path}"
        start = time.perf_counter()
        safe_error: LLMError | None = None
        try:
            resp = httpx.post(
                url,
                json=payload,
                headers=self._headers(request_id),
                timeout=self.timeout,
                trust_env=False,
                follow_redirects=False,
            )
            resp.raise_for_status()
        except httpx.TimeoutException:
            log.error("llm.timeout", path=path, timeout=self.timeout)
            safe_error = LLMError("LLM 调用超时", code="MODEL_TIMEOUT", retryable=True)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            request_id = (
                exc.response.headers.get("x-ds-trace-id")
                or exc.response.headers.get("x-request-id")
                or ""
            )
            log.error(
                "llm.http_error",
                path=path,
                status=status,
                request_id=request_id,
            )
            safe_error = LLMError(
                f"LLM 返回错误状态 {status}",
                code="MODEL_REJECTED",
                retryable=status in (408, 429) or status >= 500,
            )
        except httpx.HTTPError as exc:
            log.error(
                "llm.request_error",
                path=path,
                exception_type=type(exc).__name__,
            )
            safe_error = LLMError("LLM 请求失败", code="MODEL_UNAVAILABLE", retryable=True)

        if safe_error is not None:
            raise safe_error

        try:
            data = resp.json()
        except ValueError:
            log.error("llm.invalid_json", path=path)
            safe_error = LLMError(
                "LLM 响应格式无效",
                code="MODEL_UNAVAILABLE",
                retryable=True,
            )

        if safe_error is not None:
            raise safe_error

        latency_ms = int((time.perf_counter() - start) * 1000)
        return data, latency_ms

    def chat(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.2,
        options: ChatOptions | None = None,
    ) -> LLMResponse:
        max_output_tokens = (
            self.max_output_tokens
            if options is None or options.max_output_tokens is None
            else options.max_output_tokens
        )
        if max_output_tokens <= 0:
            raise ValueError("max_output_tokens 必须大于 0")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_output_tokens,
            "stream": False,
        }
        if options and options.response_format:
            payload["response_format"] = dict(options.response_format)
        if options and options.thinking and self.model.lower().startswith("deepseek"):
            payload["thinking"] = {"type": options.thinking}
        data, latency_ms = self._post(
            "/chat/completions",
            payload,
            request_id=options.request_id if options else None,
        )
        safe_error: LLMError | None = None
        try:
            text = data["choices"][0]["message"]["content"]
            finish_reason = data["choices"][0].get("finish_reason")
        except (KeyError, IndexError, TypeError):
            log.error("llm.bad_response", keys=list(data.keys()) if isinstance(data, dict) else type(data).__name__)
            safe_error = LLMError("LLM 响应结构异常：未找到 choices[0].message.content")
        if safe_error is not None:
            raise safe_error
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
            finish_reason=finish_reason,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = {"model": self.embed_model, "input": texts}
        data, latency_ms = self._post("/embeddings", payload)
        safe_error: LLMError | None = None
        try:
            # OpenAI 协议不保证返回顺序，按 index 排序后取 embedding
            items = sorted(data["data"], key=lambda x: x["index"])
            vectors = [item["embedding"] for item in items]
        except (KeyError, TypeError):
            log.error("llm.bad_embed_response")
            safe_error = LLMError("LLM 向量响应结构异常：未找到 data[].embedding")
        if safe_error is not None:
            raise safe_error
        log.info("llm.embed", model=self.embed_model, count=len(vectors), latency_ms=latency_ms)
        return vectors
