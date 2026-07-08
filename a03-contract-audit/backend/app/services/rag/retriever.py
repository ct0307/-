"""RAG 检索：相关法规/规则/合同模板片段。

企业责任边界的关键：审查结论必须能引用检索到的依据来源，
而非让 LLM 凭空判断。检索结果 Top-K 连同原文一起喂给审查服务。

检索策略（双后端自适应 + 降级兜底）：
  1. 优先向量检索：query embed → 与知识库切片向量算余弦相似度，取 Top-K。
     - SQLite：向量以 JSON 存 knowledge_chunks.embedding，用 numpy 内存计算。
     - PostgreSQL：同样落库，交付期可换 pgvector 原生 Vector 列 + 距离索引优化。
  2. 降级兜底：知识库为空、embedding 模型不可用（LLMError）时，
     回退到内置规则库关键词命中，保证审查链路始终可用（企业可用性刚需）。
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

# 内置最小规则库（降级兜底）：知识库无数据或 embedding 不可用时用关键词命中。
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


def retrieve(query: str, *, top_k: int = 3) -> list[dict]:
    """检索相关依据条目 [{content, source, score}]。

    优先向量检索；知识库为空或 embedding 不可用时降级为关键词命中。
    """
    db = SessionLocal()
    try:
        chunks = db.query(KnowledgeChunk).filter(KnowledgeChunk.embedding != "").all()
        if chunks:
            try:
                results = _vector_search(query, chunks, top_k)
                log.info("rag.retrieve", mode="vector", matched=len(results))
                return results
            except LLMError:
                # embedding 服务不可用，降级
                log.warning("rag.embed_unavailable", fallback="keyword")
    finally:
        db.close()

    results = _keyword_search(query, top_k)
    log.info("rag.retrieve", mode="keyword", matched=len(results))
    return results


def _vector_search(query: str, chunks: list[KnowledgeChunk], top_k: int) -> list[dict]:
    """向量检索：query embed 后与切片向量算余弦相似度，取 Top-K。"""
    adapter = get_embedding_adapter()
    query_vec = np.asarray(adapter.embed([query])[0], dtype=np.float32)

    mat = np.asarray([json.loads(c.embedding) for c in chunks], dtype=np.float32)
    # 余弦相似度 = 归一化点积；加 1e-8 防零向量除零
    q_norm = query_vec / (np.linalg.norm(query_vec) + 1e-8)
    m_norm = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-8)
    scores = m_norm @ q_norm

    top_idx = np.argsort(scores)[::-1][:top_k]
    return [
        {"content": chunks[i].content, "source": chunks[i].source, "score": round(float(scores[i]), 4)}
        for i in top_idx
    ]


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
