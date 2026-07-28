"""本地 sentence-transformers embedding 适配器。

优势：
- 完全本地化，合同数据不出企业（企业安全硬约束）
- 模型由镜像构建或运维脚本预下载到缓存；运行时只读本地，禁止隐式联网
- CPU 可跑，bge-small-zh 推理约 5-20ms/batch（生产足够）

模型选择（config LOCAL_EMBED_MODEL）：
- BAAI/bge-small-zh-v1.5（默认）：中文检索专用，384维，~100MB，MTEB 中文榜前列
- BAAI/bge-base-zh-v1.5：768维，精度稍高，~400MB
- paraphrase-multilingual-MiniLM-L12-v2：多语言，384维，~500MB
"""
import time
from functools import lru_cache

from app.core.logging import get_logger
from app.llm.base import LLMAdapter, LLMError, LLMResponse

log = get_logger("embed.local")


class LocalEmbeddingAdapter(LLMAdapter):
    """sentence-transformers 本地 embedding 适配器，仅实现 embed()。"""

    def __init__(self, model_name: str, *, normalize: bool = True) -> None:
        self.model_name = model_name
        self.normalize = normalize
        self._model = None  # 懒加载：首次 embed() 调用时才初始化，避免启动拖慢

    def _load(self):
        """加载模型（线程安全依赖 GIL，FastAPI 单进程模式下足够）。"""
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise LLMError(
                "sentence-transformers 未安装，请执行：pip install sentence-transformers"
            ) from exc
        log.info("embed.load_model", model=self.model_name)
        try:
            self._model = SentenceTransformer(self.model_name, local_files_only=True)
        except Exception as exc:
            log.error("embed.load_model_failed", model=self.model_name, error=str(exc)[:200])
            raise LLMError(f"本地 embedding 模型加载失败：{exc}") from exc
        log.info("embed.model_ready", model=self.model_name, dim=self._model.get_sentence_embedding_dimension())
        return self._model

    def chat(self, system: str, user: str, *, temperature: float = 0.2) -> LLMResponse:
        """本地 adapter 只负责 embedding，chat 不支持。业务层用 get_llm_adapter()。"""
        raise NotImplementedError(
            "LocalEmbeddingAdapter 不支持 chat()，请通过 get_llm_adapter() 获取 chat 适配器"
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        start = time.perf_counter()
        try:
            # encode() 返回 numpy ndarray，shape=(len(texts), dim)
            vectors = model.encode(texts, normalize_embeddings=self.normalize, show_progress_bar=False)
        except Exception as exc:
            log.error("embed.local_failed", error=str(exc)[:200])
            raise LLMError(f"本地 embedding 失败：{exc}") from exc
        latency_ms = int((time.perf_counter() - start) * 1000)
        log.info("embed.local_done", model=self.model_name, count=len(texts), latency_ms=latency_ms)
        return [v.tolist() for v in vectors]
