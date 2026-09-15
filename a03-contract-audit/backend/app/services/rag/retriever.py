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

条号精确短路的安全边界（2026-09-15 修复）：
  - exact 分支只对「简短的显式法条查询」触发（查询整体不超过
    _EXACT_QUERY_MAX_CHARS 字符）。审查 grounding 会把合同原文拼进查询，
    合同自身的"第X条"编号不是法条引用，必须走混合检索；调用方可传
    allow_exact=False 显式关闭（grounding 路径即如此）。
  - 本地 bge embedding 的查询侧按官方建议加检索指令前缀
    （EMBED_QUERY_PREFIX），文档侧不加；API 后端不加。
"""
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import date
from typing import Callable, Sequence

import numpy as np
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.config import settings
from app.db.session import SessionLocal
from app.llm.base import LLMError
from app.llm.factory import get_embedding_adapter
from app.models.models import KnowledgeChunk, LegalArticle
from app.services.rag.legal_sources import chinese_number_to_int, int_to_chinese_number

log = get_logger("rag")

# RRF 融合常数：排名靠后的贡献快速衰减，k=60 为检索领域经验值。
_RRF_K = 60
# 单路召回深度：每路取 Top-N 进入融合，N 略大于最终 top_k 以保证融合质量。
_PER_ROUTE_N = 30
# 向量候选最低余弦相似度。低于阈值的“最近邻”不构成可靠依据。
_MIN_VECTOR_SIMILARITY = 0.35
# 条号精确短路只接受简短的显式法条查询。拼接了合同原文的长查询里出现的
# “第X条”是合同自身条款编号，不是法条引用，不得触发 exact 分支。
_EXACT_QUERY_MAX_CHARS = 40
_CONTRACT_QUERY_TERMS = (
    "合同", "违约", "债权", "债务", "担保", "保证", "抵押", "质押",
    "价款", "租赁", "买卖", "承揽", "委托", "定金",
)
_CONTRACT_DOMAIN_SORT_BOOST = 0.002
_QUERY_EXPANSIONS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("付款", "支付", "账期", "回款"), ("付款期限", "支付条件", "验收", "逾期付款")),
    (("验收", "交付"), ("验收标准", "验收期限", "验收合格", "交付条件")),
    (("违约金", "违约"), ("违约责任", "损失赔偿", "过分高于", "适当减少")),
    (("争议", "管辖", "仲裁"), ("争议解决", "管辖法院", "仲裁机构")),
    (("解除", "终止"), ("合同解除", "终止条件", "通知期限")),
)


@dataclass(frozen=True)
class QueryPlan:
    original_query: str
    article_number: str | None
    expanded_terms: tuple[str, ...]

    @property
    def expanded_query(self) -> str:
        return " ".join((self.original_query, *self.expanded_terms)).strip()


RerankScorer = Callable[[str, Sequence[str]], Sequence[float]]

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
    allow_exact: bool = True,
) -> list[dict]:
    """检索相关依据条目 [{content, source, score}]。

    混合检索（向量 + BM25 RRF 融合）；embedding 不可用降级仅 BM25；库空降级关键词。
    allow_exact=False 关闭条号精确短路（审查 grounding 等拼接查询必须关闭，
    避免合同自身的“第X条”编号被当作法条引用劫持检索）。
    """
    plan = build_query_plan(query)
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
            KnowledgeChunk.embedding_dimension, KnowledgeChunk.scope_mode,
            KnowledgeChunk.legal_article_id, KnowledgeChunk.chunk_index,
            KnowledgeChunk.chunk_count, LegalArticle.content,
        ).outerjoin(
            LegalArticle, KnowledgeChunk.legal_article_id == LegalArticle.id
        ).all()
    finally:
        db.close()

    if not rows:
        results = _keyword_search(plan.expanded_query, top_k)
        log.info("rag.retrieve", mode="keyword", matched=len(results))
        return results

    # docs: id/content/source/embedding/category/article/version/effective/expiry/
    #       contract_types/dimensions/embedding_model/embedding_dimension/scope_mode
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

    article_number = (
        plan.article_number
        if allow_exact and len(plan.original_query) <= _EXACT_QUERY_MAX_CHARS
        else None
    )
    if article_number:
        exact_docs = [
            doc for doc in docs
            if (_doc_value(doc, 5) or _extract_article_number(doc[1])) == article_number
        ]
        if not exact_docs:
            return []
        exact_docs.sort(key=lambda doc: (
            _doc_value(doc, 14) is None,
            _doc_value(doc, 15, 0) or 0,
            doc[0],
        ))
        result = _result_from_doc(exact_docs[0], score=1.0, retrieval_mode="exact")
        log.info("rag.retrieve", mode="exact", matched=1)
        return [result]

    # —— BM25 路（全部切片参与）——
    bm25_rank = _bm25_search(plan.expanded_query, docs)

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
        results = _keyword_search(plan.expanded_query, top_k)
        log.info("rag.retrieve", mode="keyword", matched=len(results))
        return results

    mode = "hybrid" if vec_ok else "bm25"
    ranked_results = [
        _result_from_doc(id_to_doc[doc_id], score=score, retrieval_mode=mode)
        for doc_id, score in fused
    ]
    route_ranks = {
        doc_id: {
            "bm25_rank": bm25_rank.get(doc_id),
            "vector_rank": vec_rank.get(doc_id),
        }
        for doc_id, _score in fused
    }
    reranked = rerank_results(
        query,
        apply_contract_domain_boost(ranked_results, query),
        route_ranks=route_ranks,
        top_k=len(ranked_results),
        expanded_query=plan.expanded_query,
    )
    results = collapse_by_article(reranked)[:top_k]
    log.info("rag.retrieve", mode=mode, matched=len(results))
    return results


def build_query_plan(query: str) -> QueryPlan:
    """确定性生成检索计划，保留精确条号并补充有限领域同义词。"""
    normalized = re.sub(r"\s+", " ", str(query or "")).strip()
    expanded: list[str] = []
    for triggers, terms in _QUERY_EXPANSIONS:
        if any(trigger in normalized for trigger in triggers):
            for term in terms:
                if term not in normalized and term not in expanded:
                    expanded.append(term)
    return QueryPlan(
        original_query=normalized,
        article_number=parse_article_reference(normalized),
        expanded_terms=tuple(expanded),
    )


def rerank_results(
    query: str,
    candidates: list[dict],
    *,
    route_ranks: dict[int, dict[str, int | None]],
    top_k: int,
    scorer: RerankScorer | None = None,
    expanded_query: str | None = None,
) -> list[dict]:
    """对融合候选精排并附加可重放轨迹。

    scorer 用于接入本地 Cross-Encoder；未配置时采用确定性的查询覆盖度精排，
    返回值会明确记录模式，避免把降级结果伪装成模型精排。
    """
    if top_k < 1 or not candidates:
        return []
    documents = [
        str(candidate.get("matched_content") or candidate.get("content") or "")
        for candidate in candidates
    ]
    mode = "cross_encoder" if scorer is not None else "deterministic_evidence_v1"
    # 排序口径必须如实标注：cross-encoder 按精排分重排；
    # 确定性模式刻意保留 RRF 融合顺序（弱启发式不覆盖混合检索排名），
    # rerank_score 仅作观测信号记录，不得让下游误以为发生过精排。
    ordering = "rerank_score_desc" if scorer is not None else "rrf_preserved"
    if scorer is not None:
        raw_scores = [float(value) for value in scorer(query, documents)]
        if len(raw_scores) != len(candidates) or not all(math.isfinite(value) for value in raw_scores):
            raise ValueError("reranker 返回分数数量或数值无效")
    else:
        query_tokens = set(_tokenize(query))
        max_rrf = max(float(candidate.get("score") or 0.0) for candidate in candidates) or 1.0
        raw_scores = []
        for candidate, document in zip(candidates, documents):
            document_tokens = set(_tokenize(document))
            coverage = (
                len(query_tokens.intersection(document_tokens)) / len(query_tokens)
                if query_tokens else 0.0
            )
            exact_bonus = 1.0 if query.strip() and query.strip() in document else 0.0
            normalized_rrf = float(candidate.get("score") or 0.0) / max_rrf
            raw_scores.append(coverage * 0.85 + exact_bonus * 0.10 + normalized_rrf * 0.05)

    ranked: list[dict] = []
    for candidate, rerank_score in zip(candidates, raw_scores):
        item = dict(candidate)
        chunk_id = item.get("chunk_id")
        item["retrieval_trace"] = {
            "query": query,
            "expanded_query": expanded_query or query,
            "routes": dict(route_ranks.get(chunk_id, {})),
            "rrf_score": float(item.get("score") or 0.0),
            "rerank_score": round(rerank_score, 6),
            "rerank_mode": mode,
            "ordering": ordering,
        }
        ranked.append(item)
    if scorer is not None:
        ranked.sort(
            key=lambda item: (
                item["retrieval_trace"]["rerank_score"],
                float(item.get("score") or 0.0),
            ),
            reverse=True,
        )
    return ranked[:top_k]


def _result_from_doc(doc: tuple, *, score: float, retrieval_mode: str) -> dict:
    matched_content = doc[1]
    return {
        "chunk_id": doc[0],
        "matched_content": matched_content,
        "content": _doc_value(doc, 17) or matched_content,
        "source": doc[2],
        "score": round(score, 4),
        "article_number": _doc_value(doc, 5) or _extract_article_number(matched_content),
        "version": _doc_value(doc, 6),
        "retrieval_mode": retrieval_mode,
        "reliable": _doc_value(doc, 13) in {"global", "scoped"},
        "legal_article_id": _doc_value(doc, 14),
        "chunk_index": _doc_value(doc, 15),
        "chunk_count": _doc_value(doc, 16),
    }


def collapse_by_article(results: list[dict]) -> list[dict]:
    """同一父法条只保留排名最靠前的命中，旧知识记录互不合并。"""
    seen_article_ids: set[int] = set()
    collapsed: list[dict] = []
    for result in results:
        article_id = result.get("legal_article_id")
        if article_id is not None:
            if article_id in seen_article_ids:
                continue
            seen_article_ids.add(article_id)
        collapsed.append(result)
    return collapsed


def apply_contract_domain_boost(results: list[dict], query: str) -> list[dict]:
    """合同查询中小幅优先合同相关法域，不改变原始分数或过滤候选。"""
    if not any(term in query for term in _CONTRACT_QUERY_TERMS):
        return results

    def is_contract_domain(result: dict) -> bool:
        source = str(result.get("source") or "")
        if "合同编通则" in source:
            return True
        article_number = str(result.get("article_number") or "")
        match = _ARTICLE_REFERENCE_RE.search(article_number)
        if not match:
            return False
        raw = match.group("number")
        try:
            number = int(raw) if raw.isdigit() else chinese_number_to_int(raw)
        except ValueError:
            return False
        return 1 <= number <= 204 or 386 <= number <= 457 or 463 <= number <= 988

    def boosted_score(result: dict) -> float:
        score = float(result.get("score") or 0.0)
        if is_contract_domain(result):
            score += _CONTRACT_DOMAIN_SORT_BOOST
        return score

    return sorted(results, key=boosted_score, reverse=True)


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
    """按分类、作用域、合同类型、审查维度和有效期执行默认拒绝过滤。"""
    wanted_type = contract_type.strip().casefold()
    wanted_dimensions = {value.strip().casefold() for value in (dimensions or []) if value.strip()}
    wanted_categories = {value.strip().casefold() for value in (categories or []) if value.strip()}
    effective_on = as_of or date.today()
    filtered: list[tuple] = []
    for doc in docs:
        scope_mode = str(_doc_value(doc, 13, "unclassified") or "unclassified").casefold()
        if scope_mode not in {"global", "scoped"}:
            continue
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
        doc_dimensions = {value.casefold() for value in _json_string_list(_doc_value(doc, 10, "[]"))}
        if scope_mode == "scoped":
            if not contract_types and not doc_dimensions:
                continue
            if contract_types and (not wanted_type or wanted_type not in contract_types):
                continue
            if doc_dimensions and (
                not wanted_dimensions or not wanted_dimensions.intersection(doc_dimensions)
            ):
                continue
        filtered.append(doc)
    return filtered


def _vector_search(query: str, vec_docs: list[tuple]) -> dict[int, int]:
    """向量检索：返回 {doc_id: rank}（rank 从 0 起，越小越相关）。

    本地 bge 模型按官方建议在查询侧加检索指令前缀（文档侧入库时不加），
    否则短查询与训练分布不一致，检索质量明显下降；API 后端由服务商处理，不加。
    """
    adapter = get_embedding_adapter()
    query_text = query
    if settings.EMBED_BACKEND.lower() == "local" and settings.EMBED_QUERY_PREFIX:
        query_text = settings.EMBED_QUERY_PREFIX + query
    query_vectors = adapter.embed([query_text])
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


def _validate_vectors(
    vectors: list[list[float]],
    expected_count: int,
    *,
    expected_dimension: int | None = None,
) -> int:
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
    dimension = dimensions.pop()
    if expected_dimension is not None and dimension != expected_dimension:
        raise LLMError(
            f"embedding 返回维度与配置不一致：expected={expected_dimension}, actual={dimension}"
        )
    return dimension


def _configured_embedding_model() -> str:
    if settings.EMBED_BACKEND.lower() == "local":
        return settings.LOCAL_EMBED_MODEL
    return settings.EMBED_MODEL


def _configured_normalization() -> str:
    return "l2" if settings.EMBED_BACKEND.lower() == "local" else "provider-default"


def embedding_signature(
    *,
    backend: str,
    model: str,
    dimension: int,
    normalization: str,
    chunk_schema_version: str,
) -> str:
    payload = {
        "backend": backend,
        "model": model,
        "dimension": dimension,
        "normalization": normalization,
        "chunk_schema_version": chunk_schema_version,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
_ARTICLE_NUMERAL_CHARS = "零〇一二两三四五六七八九十百千万"
_ARTICLE_REFERENCE_RE = re.compile(
    rf"(?<![\d{_ARTICLE_NUMERAL_CHARS}])(?:第)?"
    rf"(?P<number>\d{{1,4}}|[{_ARTICLE_NUMERAL_CHARS}]{{1,7}})条"
    rf"(?:之(?P<suffix>\d{{1,4}}|[{_ARTICLE_NUMERAL_CHARS}]{{1,7}}))?"
    rf"(?![之\d{_ARTICLE_NUMERAL_CHARS}])"
)


def parse_article_reference(query: str) -> str | None:
    """从查询中提取条号并统一为中文规范形式。"""
    match = _ARTICLE_REFERENCE_RE.search(query or "")
    if not match:
        return None
    raw_number = match.group("number")
    try:
        number = int(raw_number) if raw_number.isdigit() else chinese_number_to_int(raw_number)
        raw_suffix = match.group("suffix")
        suffix = (
            int(raw_suffix) if raw_suffix and raw_suffix.isdigit()
            else chinese_number_to_int(raw_suffix) if raw_suffix
            else None
        )
    except ValueError:
        return None
    if not 1 <= number < 10000:
        return None
    normalized = f"第{int_to_chinese_number(number)}条"
    if suffix is not None:
        if not 1 <= suffix < 10000:
            return None
        normalized += f"之{int_to_chinese_number(suffix)}"
    return normalized


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
                "matched_content": rule["content"],
                "source": rule["source"],
                "source_type": "fallback_rule",
                "article_number": None,
                "score": hits,
                "retrieval_mode": "fallback",
                "reliable": False,
                "legal_article_id": None,
                "chunk_index": None,
                "chunk_count": None,
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


def prepare_documents(
    chunks: list[dict],
    *,
    embedding_cache: dict[tuple[str, str], list[float]] | None = None,
) -> list[KnowledgeChunk]:
    """在数据库事务外生成并校验全部向量，返回尚未持久化的 ORM 行。"""
    if not chunks:
        return []
    chunks = [_normalize_chunk_scope(chunk) for chunk in chunks]
    embedding_cache = embedding_cache or {}
    embedding_model = _configured_embedding_model()
    embedding_inputs = [chunk.get("retrieval_text") or chunk["content"] for chunk in chunks]
    content_hashes = [
        hashlib.sha256(text.encode("utf-8")).hexdigest() for text in embedding_inputs
    ]
    signatures: list[str | None] = []
    vectors: list[list[float] | None] = [None] * len(chunks)
    missing_indexes: list[int] = []

    for index, (chunk, content_hash) in enumerate(zip(chunks, content_hashes)):
        schema_version = chunk.get("chunk_schema_version")
        signature = None
        if schema_version:
            signature = embedding_signature(
                backend=settings.EMBED_BACKEND.lower(),
                model=embedding_model,
                dimension=settings.EMBED_DIM,
                normalization=_configured_normalization(),
                chunk_schema_version=schema_version,
            )
            cached = embedding_cache.get((content_hash, signature))
            parsed = _coerce_vector(cached) if cached is not None else None
            if parsed is not None and parsed.size == settings.EMBED_DIM:
                vectors[index] = cached
        signatures.append(signature)
        if vectors[index] is None:
            missing_indexes.append(index)

    if missing_indexes:
        adapter = get_embedding_adapter()
        generated = adapter.embed([embedding_inputs[index] for index in missing_indexes])
        _validate_vectors(generated, len(missing_indexes))
        for index, vector in zip(missing_indexes, generated):
            if signatures[index] and len(vector) != settings.EMBED_DIM:
                raise LLMError(
                    "embedding 返回维度与配置不一致："
                    f"expected={settings.EMBED_DIM}, actual={len(vector)}"
                )
            vectors[index] = vector

    complete_vectors = [vector for vector in vectors if vector is not None]
    dimension = _validate_vectors(complete_vectors, len(chunks))
    return [
        _knowledge_row(
            chunk,
            embedding=json.dumps(vector),
            embedding_model=embedding_model,
            embedding_dimension=dimension,
            embedding_signature_value=signature,
            content_hash_value=content_hash,
        )
        for chunk, vector, signature, content_hash in zip(
            chunks, complete_vectors, signatures, content_hashes
        )
    ]


def build_documents_without_embeddings(chunks: list[dict]) -> list[KnowledgeChunk]:
    """Embedding 不可用时生成空向量行，保留 BM25 检索能力。"""
    return [
        _knowledge_row(
            _normalize_chunk_scope(chunk),
            embedding="",
            embedding_model=None,
            embedding_dimension=None,
        )
        for chunk in chunks
    ]


def normalize_scope_metadata(
    scope_mode: str = "unclassified",
    applicable_contract_types=None,
    applicable_dimensions=None,
) -> dict:
    """规范化知识作用域；`scoped` 缺少目标时默认拒绝。"""
    normalized_mode = str(scope_mode or "unclassified").strip().casefold()
    if normalized_mode not in {"global", "scoped", "unclassified"}:
        raise ValueError("scope_mode must be global, scoped, or unclassified")
    contract_types = _json_string_list(applicable_contract_types)
    dimensions = _json_string_list(applicable_dimensions)
    if normalized_mode == "scoped" and not contract_types and not dimensions:
        raise ValueError("scoped knowledge requires a contract type or audit dimension")
    return {
        "scope_mode": normalized_mode,
        "applicable_contract_types": contract_types,
        "applicable_dimensions": dimensions,
    }


def _normalize_chunk_scope(chunk: dict) -> dict:
    metadata = normalize_scope_metadata(
        chunk.get("scope_mode", "unclassified"),
        chunk.get("applicable_contract_types", []),
        chunk.get("applicable_dimensions", []),
    )
    return {**chunk, **metadata}


def controlled_seed_scope(category: str, source: str) -> dict:
    """为仓库内受控种子赋作用域，不推断任意历史知识。"""
    normalized_category = category.strip().casefold()
    if normalized_category == "law" and source.startswith("《民法典》"):
        return normalize_scope_metadata("global")
    if "软件" in source or "技术类合同" in source:
        return normalize_scope_metadata("scoped", ["软件开发外包合同"], [])
    if "采购合同" in source:
        return normalize_scope_metadata("scoped", ["采购合同", "设备采购合同"], [])
    if normalized_category in {"rule", "template"}:
        return normalize_scope_metadata("global")
    return normalize_scope_metadata("unclassified")


def _knowledge_row(
    chunk: dict,
    *,
    embedding: str,
    embedding_model: str | None,
    embedding_dimension: int | None,
    embedding_signature_value: str | None = None,
    content_hash_value: str | None = None,
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
        scope_mode=chunk.get("scope_mode", "unclassified"),
        embedding_model=embedding_model,
        embedding_dimension=embedding_dimension,
        content_hash=content_hash_value or hashlib.sha256(
            (chunk.get("retrieval_text") or chunk["content"]).encode("utf-8")
        ).hexdigest(),
        legal_article_id=chunk.get("legal_article_id"),
        chunk_index=chunk.get("chunk_index"),
        chunk_count=chunk.get("chunk_count"),
        chunk_schema_version=chunk.get("chunk_schema_version"),
        retrieval_text=chunk.get("retrieval_text"),
        embedding_signature=embedding_signature_value,
    )
