"""RAG 检索：相关法规/规则/合同模板片段。

企业责任边界的关键：审查结论必须能引用检索到的依据来源，
而非让 LLM 凭空判断。检索结果 Top-K 连同原文一起喂给审查服务。

检索策略（混合检索 + 降级兜底）：
  1. 混合检索（默认）：向量语义 + BM25 词频，两路排名用 RRF 融合取 Top-K。
     - 向量路：query embed → 与知识库切片向量算余弦相似度（仅非空向量参与）。
     - BM25 路：jieba 中文分词 → BM25 词频打分（全部切片参与，法条术语精确匹配强）。
     - RRF 融合：score = Σ 1/(k + rank)，两路互补，召回与精度均优于单路。
  2. 降级兜底（保证审查链路始终可用，企业可用性刚需）：
     - embedding 不可用（LLMError）→ 仅 BM25 路。
     - 知识库为空 → 内置规则库关键词命中。

BM25 索引带正文内容指纹缓存，知识正文或 ID 变化时自动重建。
"""
import hashlib
import json
import re
from datetime import date

import numpy as np
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.config import settings
from app.db.session import SessionLocal
from app.llm.base import LLMError
from app.llm.factory import get_embedding_adapter
from app.models.models import KnowledgeChunk

log = get_logger("rag")

# RRF 融合常数：排名靠后的贡献快速衰减，k=60 为检索领域经验值。
_RRF_K = 60
# 单路召回深度：每路取 Top-N 进入融合，N 略大于最终 top_k 以保证融合质量。
_PER_ROUTE_N = 10
# 向量候选最低余弦相似度。低于阈值的“最近邻”不构成可靠依据。
_MIN_VECTOR_SIMILARITY = 0.35

# 内置最小规则库（降级兜底）：知识库无数据时用关键词命中。
# 每条 = {content: 依据内容, source: 来源, keywords: 命中关键词}
_FALLBACK_RULES: list[dict] = [
    {
        "content": "合同应明确约定违约责任，否则守约方难以主张违约金或损失赔偿。",
        "source": "内置违约责任审查规则",
        "keywords": ["违约", "违约责任", "违约金"],
    },
    {
        "content": "合同应约定争议解决方式（仲裁或诉讼管辖），避免纠纷时管辖不明。",
        "source": "内置争议解决审查规则",
        "keywords": ["争议", "仲裁", "诉讼", "管辖"],
    },
    {
        "content": "合同金额应大小写一致并明确币种，避免金额争议。",
        "source": "内置合同金额审查规则",
        "keywords": ["金额", "价款", "元", "人民币"],
    },
    {
        "content": "合同应明确履约期限的起止时间，作为违约判定和验收依据。",
        "source": "内置履约期限审查规则",
        "keywords": ["期限", "履约", "有效期"],
    },
]

# BM25 索引缓存：{fingerprint, bm25, docs}。docs 为纯数据元组，不持 ORM 对象。
_bm25_cache: dict | None = None


def retrieve(
    query: str,
    *,
    top_k: int = 3,
    contract_type: str = "",
    dimensions: list[str] | None = None,
    categories: list[str] | None = None,
    as_of: date | None = None,
) -> list[dict]:
    """检索相关依据条目 [{content, source, score}]。

    混合检索（向量 + BM25 RRF 融合）；embedding 不可用降级仅 BM25；库空降级关键词。
    """
    db = SessionLocal()
    try:
        # 一次取全量切片（BM25 需全部；向量路只用非空向量）
        rows = db.query(
            KnowledgeChunk.id, KnowledgeChunk.content,
            KnowledgeChunk.source, KnowledgeChunk.embedding,
            KnowledgeChunk.category, KnowledgeChunk.article_number,
            KnowledgeChunk.version, KnowledgeChunk.effective_date,
            KnowledgeChunk.expiry_date, KnowledgeChunk.applicable_contract_types,
            KnowledgeChunk.applicable_dimensions, KnowledgeChunk.embedding_model,
            KnowledgeChunk.embedding_dimension,
        ).all()
    finally:
        db.close()

    if not rows:
        results = _keyword_search(query, top_k)
        log.info("rag.retrieve", mode="keyword", matched=len(results))
        return results

    # docs: id/content/source/embedding/category/article/version/effective/expiry/
    #       contract_types/dimensions/embedding_model/embedding_dimension
    docs = [tuple(r) for r in rows]
    docs = _filter_docs(
        docs,
        contract_type=contract_type,
        dimensions=dimensions or [],
        categories=categories or [],
        as_of=as_of or date.today(),
    )
    if not docs:
        log.info("rag.retrieve", mode="filtered_empty", matched=0)
        return []

    # —— BM25 路（全部切片参与）——
    bm25_rank = _bm25_search(query, docs)

    # —— 向量路（仅非空向量参与）——
    vec_rank: dict[int, int] = {}
    vec_ok = False
    vec_docs = [d for d in docs if d[3]]
    if vec_docs:
        try:
            vec_rank = _vector_search(query, vec_docs)
            vec_ok = True
        except LLMError:
            log.warning("rag.embed_unavailable", fallback="bm25_only")

    # —— RRF 融合 ——
    id_to_doc = {d[0]: d for d in docs}
    fused = _rrf_fuse([vec_rank, bm25_rank])
    if not fused:
        # 两路都空（极端：query 无分词命中且无向量），回退关键词
        results = _keyword_search(query, top_k)
        log.info("rag.retrieve", mode="keyword", matched=len(results))
        return results

    results = []
    for doc_id, score in fused[:top_k]:
        doc = id_to_doc[doc_id]
        results.append({
            "chunk_id": doc_id,
            "content": doc[1],
            "source": doc[2],
            "score": round(score, 4),
            "article_number": _doc_value(doc, 5) or _extract_article_number(doc[1]),
            "version": _doc_value(doc, 6),
            "retrieval_mode": "hybrid" if vec_ok else "bm25",
            "reliable": True,
        })

    mode = "hybrid" if vec_ok else "bm25"
    log.info("rag.retrieve", mode=mode, matched=len(results))
    return results


def _doc_value(doc: tuple, index: int, default=None):
    return doc[index] if len(doc) > index else default


def _json_string_list(raw) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        values = raw
    else:
        try:
            values = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return []
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _filter_docs(
    docs: list[tuple],
    *,
    contract_type: str = "",
    dimensions: list[str] | None = None,
    categories: list[str] | None = None,
    as_of: date | None = None,
) -> list[tuple]:
    """按分类、合同类型、审查维度和有效期过滤；缺失元数据表示不限制。"""
    wanted_type = contract_type.strip().casefold()
    wanted_dimensions = {value.strip().casefold() for value in (dimensions or []) if value.strip()}
    wanted_categories = {value.strip().casefold() for value in (categories or []) if value.strip()}
    effective_on = as_of or date.today()
    filtered: list[tuple] = []
    for doc in docs:
        category = str(_doc_value(doc, 4, "") or "").casefold()
        if wanted_categories and category not in wanted_categories:
            continue
        effective_date = _doc_value(doc, 7)
        expiry_date = _doc_value(doc, 8)
        if effective_date and effective_date > effective_on:
            continue
        if expiry_date and expiry_date < effective_on:
            continue
        contract_types = {value.casefold() for value in _json_string_list(_doc_value(doc, 9, "[]"))}
        if wanted_type and contract_types and wanted_type not in contract_types:
            continue
        doc_dimensions = {value.casefold() for value in _json_string_list(_doc_value(doc, 10, "[]"))}
        if wanted_dimensions and doc_dimensions and not wanted_dimensions.intersection(doc_dimensions):
            continue
        filtered.append(doc)
    return filtered


def _vector_search(query: str, vec_docs: list[tuple]) -> dict[int, int]:
    """向量检索：返回 {doc_id: rank}（rank 从 0 起，越小越相关）。"""
    adapter = get_embedding_adapter()
    query_vectors = adapter.embed([query])
    if len(query_vectors) != 1:
        raise LLMError(f"embedding 查询向量数量异常：expected=1, actual={len(query_vectors)}")
    query_vec = _coerce_vector(query_vectors[0])
    if query_vec is None:
        raise LLMError("embedding 查询向量格式无效")

    valid_docs: list[tuple] = []
    valid_vectors: list[np.ndarray] = []
    expected_model = _configured_embedding_model()
    for doc in vec_docs:
        stored_model = _doc_value(doc, 11)
        if stored_model != expected_model:
            log.warning(
                "rag.embedding_model_mismatch",
                chunk_id=doc[0], stored_model=stored_model, query_model=expected_model,
            )
            continue
        vector = _parse_stored_vector(doc[3])
        if vector is None:
            log.warning("rag.invalid_stored_vector", chunk_id=doc[0])
            continue
        if vector.size != query_vec.size:
            log.warning(
                "rag.embedding_dimension_mismatch",
                chunk_id=doc[0], stored_dim=vector.size, query_dim=query_vec.size,
            )
            continue
        valid_docs.append(doc)
        valid_vectors.append(vector)
    if not valid_docs:
        return {}

    mat = np.stack(valid_vectors)
    q_norm = query_vec / (np.linalg.norm(query_vec) + 1e-8)
    m_norm = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-8)
    scores = m_norm @ q_norm

    order = [idx for idx in np.argsort(scores)[::-1] if scores[idx] >= _MIN_VECTOR_SIMILARITY]
    return {valid_docs[idx][0]: rank for rank, idx in enumerate(order[:_PER_ROUTE_N])}


def _coerce_vector(value) -> np.ndarray | None:
    """把向量转换为有限的一维 float32 数组；格式无效时返回 None。"""
    try:
        vector = np.asarray(value, dtype=np.float32)
    except (TypeError, ValueError):
        return None
    if vector.ndim != 1 or vector.size == 0 or not np.isfinite(vector).all():
        return None
    return vector


def _parse_stored_vector(raw: str) -> np.ndarray | None:
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    return _coerce_vector(value)


def _validate_vectors(vectors: list[list[float]], expected_count: int) -> int:
    """校验整批 embedding 数量、数值和维度，返回统一维度。"""
    if len(vectors) != expected_count:
        raise LLMError(
            f"embedding 返回数量不一致：expected={expected_count}, actual={len(vectors)}"
        )
    parsed = [_coerce_vector(value) for value in vectors]
    if any(vector is None for vector in parsed):
        raise LLMError("embedding 返回了空值、非数值或非有限向量")
    dimensions = {vector.size for vector in parsed if vector is not None}
    if len(dimensions) != 1:
        raise LLMError("embedding 返回向量维度不一致")
    return dimensions.pop()


def _configured_embedding_model() -> str:
    if settings.EMBED_BACKEND.lower() == "local":
        return settings.LOCAL_EMBED_MODEL
    return settings.EMBED_MODEL


def _bm25_search(query: str, docs: list[tuple]) -> dict[int, int]:
    """BM25 检索：返回 {doc_id: rank}（rank 从 0 起，越小越相关）。

    命中数为 0（query 无词落在语料）时返回空 dict。
    """
    bm25, doc_ids = _get_bm25_index(docs)
    tokens = _tokenize(query)
    if not tokens:
        return {}
    scores = bm25.get_scores(tokens)
    order = np.argsort(scores)[::-1]
    # 过滤 0 分（完全未命中）避免噪音进融合
    ranked = [(doc_ids[idx], rank) for rank, idx in enumerate(order) if scores[idx] > 0]
    ranked = ranked[:_PER_ROUTE_N]
    return {doc_id: rank for doc_id, rank in ranked}


def _rrf_fuse(rank_maps: list[dict[int, int]]) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion：融合多路 {doc_id: rank}，返回按融合分降序的 [(doc_id, score)]。"""
    fused: dict[int, float] = {}
    for rmap in rank_maps:
        for doc_id, rank in rmap.items():
            fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (_RRF_K + rank)
    return sorted(fused.items(), key=lambda x: x[1], reverse=True)


def _get_bm25_index(docs: list[tuple]):
    """构建/复用 BM25 索引。文档 ID 或正文变化时重建。"""
    global _bm25_cache
    from rank_bm25 import BM25Okapi

    fingerprint = _docs_fingerprint(docs)
    if _bm25_cache and _bm25_cache["fingerprint"] == fingerprint:
        return _bm25_cache["bm25"], _bm25_cache["doc_ids"]

    corpus = [_tokenize(d[1]) for d in docs]
    bm25 = BM25Okapi(corpus)
    doc_ids = [d[0] for d in docs]
    _bm25_cache = {"fingerprint": fingerprint, "bm25": bm25, "doc_ids": doc_ids}
    log.info("rag.bm25_index_built", docs=len(docs))
    return bm25, doc_ids


def _docs_fingerprint(docs: list[tuple]) -> str:
    digest = hashlib.sha256()
    for doc in docs:
        digest.update(f"{doc[0]}\x00{doc[1]}\x00".encode("utf-8"))
    return digest.hexdigest()


_ARTICLE_NUMBER_RE = re.compile(
    r"第[一二三四五六七八九十百千零两\d]{1,7}条(?:之[一二三四五六七八九十\d]+)?"
)


def _extract_article_number(content: str) -> str | None:
    match = _ARTICLE_NUMBER_RE.search(content or "")
    return match.group(0) if match else None


def _tokenize(text: str) -> list[str]:
    """jieba 中文分词，去除单字符空白 token。首次调用加载词典（懒加载单例）。"""
    import jieba

    return [t for t in jieba.lcut(text) if t.strip()]


def _keyword_search(query: str, top_k: int) -> list[dict]:
    """降级：内置规则库关键词命中，命中数越多分越高。"""
    scored: list[dict] = []
    for rule in _FALLBACK_RULES:
        hits = sum(1 for kw in rule["keywords"] if kw in query)
        if hits:
            scored.append({
                "chunk_id": None,
                "content": rule["content"],
                "source": rule["source"],
                "source_type": "fallback_rule",
                "article_number": None,
                "score": hits,
                "retrieval_mode": "fallback",
                "reliable": True,
            })
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


def index_documents(chunks: list[dict], db: Session | None = None) -> int:
    """知识库切片向量化入库，返回写入条数。

    chunks: [{category, source, content}]。逐批 embed 后落库 knowledge_chunks。
    embedding 不可用时抛 LLMError，由调用方处理（不静默写入空向量）。
    """
    if not chunks:
        return 0
    own_db = db is None
    db = db or SessionLocal()
    try:
        rows = prepare_documents(chunks)
        for row in rows:
            db.add(row)
        db.commit()
        log.info("rag.index", count=len(chunks))
        return len(chunks)
    finally:
        if own_db:
            db.close()


def prepare_documents(chunks: list[dict]) -> list[KnowledgeChunk]:
    """在数据库事务外生成并校验全部向量，返回尚未持久化的 ORM 行。"""
    if not chunks:
        return []
    adapter = get_embedding_adapter()
    vectors = adapter.embed([chunk["content"] for chunk in chunks])
    dimension = _validate_vectors(vectors, len(chunks))
    embedding_model = _configured_embedding_model()
    return [
        _knowledge_row(
            chunk,
            embedding=json.dumps(vector),
            embedding_model=embedding_model,
            embedding_dimension=dimension,
        )
        for chunk, vector in zip(chunks, vectors)
    ]


def build_documents_without_embeddings(chunks: list[dict]) -> list[KnowledgeChunk]:
    """Embedding 不可用时生成空向量行，保留 BM25 检索能力。"""
    return [
        _knowledge_row(chunk, embedding="", embedding_model=None, embedding_dimension=None)
        for chunk in chunks
    ]


def _knowledge_row(
    chunk: dict,
    *,
    embedding: str,
    embedding_model: str | None,
    embedding_dimension: int | None,
) -> KnowledgeChunk:
    return KnowledgeChunk(
        category=chunk.get("category", "rule"),
        source=chunk.get("source", ""),
        content=chunk["content"],
        embedding=embedding,
        article_number=chunk.get("article_number") or _extract_article_number(chunk["content"]),
        version=chunk.get("version"),
        effective_date=chunk.get("effective_date"),
        expiry_date=chunk.get("expiry_date"),
        applicable_contract_types=json.dumps(
            chunk.get("applicable_contract_types", []), ensure_ascii=False
        ),
        applicable_dimensions=json.dumps(
            chunk.get("applicable_dimensions", []), ensure_ascii=False
        ),
        embedding_model=embedding_model,
        embedding_dimension=embedding_dimension,
        content_hash=hashlib.sha256(chunk["content"].encode("utf-8")).hexdigest(),
    )
