"""权威法律知识的只读规划与原子同步。"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.models import KnowledgeChunk, LegalArticle, LegalSource
from app.services.rag import retriever
from app.services.rag.legal_sources import (
    ParsedArticle,
    SourceSpec,
    load_manifest,
    parse_articles,
    split_legal_article,
    validate_article_set,
    verify_source_file,
)


_LEGACY_SOURCES = ("民法典-合同编.txt",)


@dataclass(frozen=True)
class SyncReport:
    source_count: int
    article_count: int
    chunk_count: int
    reuse_embedding_count: int
    rebuild_embedding_count: int
    replace_chunk_count: int
    replace_legacy: bool


@dataclass(frozen=True)
class LegalBundle:
    specs: tuple[SourceSpec, ...]
    articles: tuple[ParsedArticle, ...]
    chunks: tuple[dict, ...]


def _load_bundle(manifest_path: Path) -> LegalBundle:
    specs = load_manifest(manifest_path)
    articles: list[ParsedArticle] = []
    chunks: list[dict] = []
    for spec in specs:
        text = verify_source_file(spec, manifest_path.parent)
        source_articles = parse_articles(spec, text)
        validate_article_set(spec, source_articles)
        articles.extend(source_articles)
        for article in source_articles:
            for chunk in split_legal_article(article, source_title=spec.title):
                chunks.append({
                    "category": "law",
                    "source": spec.title,
                    "content": chunk.display_content,
                    "retrieval_text": chunk.retrieval_text,
                    "article_number": chunk.article_number,
                    "article_key": chunk.article_key,
                    "chunk_index": chunk.chunk_index,
                    "chunk_count": chunk.chunk_count,
                    "chunk_schema_version": chunk.chunk_schema_version,
                    "version": f"{spec.publication_date.isoformat()} {spec.version_status}",
                    "effective_date": spec.effective_date,
                    "scope_mode": "global",
                })
    return LegalBundle(tuple(specs), tuple(articles), tuple(chunks))


def _embedding_cache(db: Session) -> dict[tuple[str, str], list[float]]:
    cache: dict[tuple[str, str], list[float]] = {}
    rows = db.query(
        KnowledgeChunk.content_hash,
        KnowledgeChunk.embedding_signature,
        KnowledgeChunk.embedding,
    ).filter(
        KnowledgeChunk.content_hash.isnot(None),
        KnowledgeChunk.embedding_signature.isnot(None),
        KnowledgeChunk.embedding != "",
    ).all()
    for content_hash, signature, raw_embedding in rows:
        try:
            vector = json.loads(raw_embedding)
        except (TypeError, json.JSONDecodeError):
            continue
        parsed = retriever._coerce_vector(vector)
        if parsed is None or parsed.size != settings.EMBED_DIM:
            continue
        cache[(content_hash, signature)] = vector
    return cache


def _chunk_cache_key(chunk: dict) -> tuple[str, str]:
    retrieval_text = chunk["retrieval_text"]
    content_hash = hashlib.sha256(retrieval_text.encode("utf-8")).hexdigest()
    signature = retriever.embedding_signature(
        backend=settings.EMBED_BACKEND.lower(),
        model=retriever._configured_embedding_model(),
        dimension=settings.EMBED_DIM,
        normalization=retriever._configured_normalization(),
        chunk_schema_version=chunk["chunk_schema_version"],
    )
    return content_hash, signature


def _report(
    db: Session,
    bundle: LegalBundle,
    *,
    replace_legacy: bool,
) -> tuple[SyncReport, dict[tuple[str, str], list[float]]]:
    cache = _embedding_cache(db)
    reuse_count = sum(1 for chunk in bundle.chunks if _chunk_cache_key(chunk) in cache)
    source_ids = [spec.source_id for spec in bundle.specs]
    article_ids = db.query(LegalArticle.id).filter(LegalArticle.source_id.in_(source_ids))
    replace_count = db.query(KnowledgeChunk).filter(
        KnowledgeChunk.legal_article_id.in_(article_ids)
    ).count()
    if replace_legacy:
        replace_count += db.query(KnowledgeChunk).filter(
            KnowledgeChunk.source.in_(_LEGACY_SOURCES)
        ).count()
    return SyncReport(
        source_count=len(bundle.specs),
        article_count=len(bundle.articles),
        chunk_count=len(bundle.chunks),
        reuse_embedding_count=reuse_count,
        rebuild_embedding_count=len(bundle.chunks) - reuse_count,
        replace_chunk_count=replace_count,
        replace_legacy=replace_legacy,
    ), cache


def plan_legal_sync(
    db: Session,
    manifest_path: Path,
    *,
    replace_legacy: bool = False,
) -> SyncReport:
    bundle = _load_bundle(manifest_path)
    report, _ = _report(db, bundle, replace_legacy=replace_legacy)
    return report


def apply_legal_sync(
    db: Session,
    manifest_path: Path,
    *,
    replace_legacy: bool = False,
) -> SyncReport:
    bundle = _load_bundle(manifest_path)
    report, cache = _report(db, bundle, replace_legacy=replace_legacy)

    # 所有向量在数据库替换前完成；失败时旧知识不受影响。
    rows = retriever.prepare_documents(list(bundle.chunks), embedding_cache=cache)
    source_ids = [spec.source_id for spec in bundle.specs]
    db.rollback()
    with db.begin():
        article_ids = db.query(LegalArticle.id).filter(LegalArticle.source_id.in_(source_ids))
        db.query(KnowledgeChunk).filter(
            KnowledgeChunk.legal_article_id.in_(article_ids)
        ).delete(synchronize_session=False)
        if replace_legacy:
            db.query(KnowledgeChunk).filter(
                KnowledgeChunk.source.in_(_LEGACY_SOURCES)
            ).delete(synchronize_session=False)
        db.query(LegalArticle).filter(
            LegalArticle.source_id.in_(source_ids)
        ).delete(synchronize_session=False)
        db.query(LegalSource).filter(
            LegalSource.source_id.in_(source_ids)
        ).delete(synchronize_session=False)

        for spec in bundle.specs:
            db.add(LegalSource(
                source_id=spec.source_id,
                title=spec.title,
                issuing_authority=spec.issuing_authority,
                official_url=spec.official_url,
                publication_date=spec.publication_date,
                effective_date=spec.effective_date,
                version_status=spec.version_status,
                retrieved_at=spec.retrieved_at,
                file_sha256=spec.file_sha256,
            ))
        db.flush()

        article_rows: dict[tuple[str, str], LegalArticle] = {}
        for article in bundle.articles:
            row = LegalArticle(
                source_id=article.source_id,
                article_number=article.article_number,
                article_sort=article.article_sort,
                chapter_title=article.chapter_title,
                content=article.content,
                content_hash=article.content_hash,
            )
            db.add(row)
            article_rows[(article.source_id, article.article_number)] = row
        db.flush()

        for chunk, row in zip(bundle.chunks, rows):
            row.legal_article_id = article_rows[chunk["article_key"]].id
            db.add(row)
    return report
