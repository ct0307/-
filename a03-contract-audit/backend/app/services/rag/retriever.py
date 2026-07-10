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

BM25 索引带指纹缓存（chunk 数 + max id），知识库变动时自动重建。
"""
import json

import numpy as np
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.llm.base import LLMError
from app.llm.factory import get_embedding_adapter
from app.models.models import KnowledgeChunk

log = get_logger("rag")

# RRF 融合常数：排名靠后的贡献快速衰减，k=60 为检索领域经验值。
_RRF_K = 60
# 单路召回深度：每路取 Top-N 进入融合，N 略大于最终 top_k 以保证融合质量。
_PER_ROUTE_N = 10

# 内置最小规则库（降级兜底）：知识库无数据时用关键词命中。
# 每条 = {content: 依据内容, source: 来源, keywords: 命中关键词}
_FALLBACK_RULES: list[dict] = [
    {
        "content": "合同应明确约定违约责任，否则守约方难以主张违约金或损失赔偿。",
        "source": "《民法典》第577条 / 企业合同管理规范",
        "keywords": ["违约", "违约责任", "违约金"],
    },
    {
        "content": "合同应约定争议解决方式（仲裁或诉讼管辖），避免纠纷时管辖不明。",
        "source": "《民法典》第502条 / 争议解决条款指引",
        "keywords": ["争议", "仲裁", "诉讼", "管辖"],
    },
    {
        "content": "合同金额应大小写一致并明确币种，避免金额争议。",
        "source": "企业合同金额条款标准",
        "keywords": ["金额", "价款", "元", "人民币"],
    },
    {
        "content": "合同应明确履约期限的起止时间，作为违约判定和验收依据。",
        "source": "企业合同履约条款标准",
        "keywords": ["期限", "履约", "有效期"],
    },
]

# BM25 索引缓存：{fingerprint, bm25, docs}。docs 为纯数据元组，不持 ORM 对象。
_bm25_cache: dict | None = None


def retrieve(query: str, *, top_k: int = 3) -> list[dict]:
    """检索相关依据条目 [{content, source, score}]。

    混合检索（向量 + BM25 RRF 融合）；embedding 不可用降级仅 BM25；库空降级关键词。
    """
    db = SessionLocal()
    try:
        # 一次取全量切片（BM25 需全部；向量路只用非空向量）
        rows = db.query(
            KnowledgeChunk.id, KnowledgeChunk.content,
            KnowledgeChunk.source, KnowledgeChunk.embedding,
        ).all()
    finally:
        db.close()

    if not rows:
        results = _keyword_search(query, top_k)
        log.info("rag.retrieve", mode="keyword", matched=len(results))
        return results

    # docs: [(id, content, source, embedding_json)]
    docs = [(r.id, r.content, r.source, r.embedding) for r in rows]

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
        _id, content, source, _emb = id_to_doc[doc_id]
        results.append({"content": content, "source": source, "score": round(score, 4)})

    mode = "hybrid" if vec_ok else "bm25"
    log.info("rag.retrieve", mode=mode, matched=len(results))
    return results


def _vector_search(query: str, vec_docs: list[tuple]) -> dict[int, int]:
    """向量检索：返回 {doc_id: rank}（rank 从 0 起，越小越相关）。"""
    adapter = get_embedding_adapter()
    query_vec = np.asarray(adapter.embed([query])[0], dtype=np.float32)

    mat = np.asarray([json.loads(d[3]) for d in vec_docs], dtype=np.float32)
    q_norm = query_vec / (np.linalg.norm(query_vec) + 1e-8)
    m_norm = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-8)
    scores = m_norm @ q_norm

    order = np.argsort(scores)[::-1]  # 相似度降序
    return {vec_docs[idx][0]: rank for rank, idx in enumerate(order)}


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
    return {doc_id: rank for doc_id, rank in ranked}


def _rrf_fuse(rank_maps: list[dict[int, int]]) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion：融合多路 {doc_id: rank}，返回按融合分降序的 [(doc_id, score)]。"""
    fused: dict[int, float] = {}
    for rmap in rank_maps:
        for doc_id, rank in rmap.items():
            fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (_RRF_K + rank)
    return sorted(fused.items(), key=lambda x: x[1], reverse=True)


def _get_bm25_index(docs: list[tuple]):
    """构建/复用 BM25 索引。指纹（切片数 + 最大 id）变化时重建。"""
    global _bm25_cache
    from rank_bm25 import BM25Okapi

    fingerprint = (len(docs), max((d[0] for d in docs), default=0))
    if _bm25_cache and _bm25_cache["fingerprint"] == fingerprint:
        return _bm25_cache["bm25"], _bm25_cache["doc_ids"]

    corpus = [_tokenize(d[1]) for d in docs]
    bm25 = BM25Okapi(corpus)
    doc_ids = [d[0] for d in docs]
    _bm25_cache = {"fingerprint": fingerprint, "bm25": bm25, "doc_ids": doc_ids}
    log.info("rag.bm25_index_built", docs=len(docs))
    return bm25, doc_ids


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
            scored.append({"content": rule["content"], "source": rule["source"], "score": hits})
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
        adapter = get_embedding_adapter()
        vectors = adapter.embed([c["content"] for c in chunks])
        for chunk, vec in zip(chunks, vectors):
            db.add(KnowledgeChunk(
                category=chunk.get("category", "rule"),
                source=chunk.get("source", ""),
                content=chunk["content"],
                embedding=json.dumps(vec),
            ))
        db.commit()
        log.info("rag.index", count=len(chunks))
        return len(chunks)
    finally:
        if own_db:
            db.close()
