"""从前端上传的文件预检并应用权威法律知识。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import BASE_DIR, settings
from app.models.models import KnowledgeChunk, LegalArticle, LegalSource
from app.services.rag import retriever
from app.services.rag.legal_sync import _chunk_cache_key, _embedding_cache
from app.services.rag.legal_sources import (
    LegalSourceError,
    SourceSpec,
    load_manifest,
    parse_articles,
    split_legal_article,
    validate_article_set,
)


_MANIFEST_PATH = BASE_DIR / "resources" / "legal_sources" / "manifest.json"
_CIVIL_CODE_SOURCE_ID = "civil-code-2020"
_TOKEN_TTL = timedelta(minutes=10)


class LegalImportError(ValueError):
    """权威法源导入请求无效。"""


@dataclass(frozen=True)
class LegalImportPreview:
    candidate: bool
    allowed: bool
    source_id: str | None
    title: str | None
    file_sha256: str
    hash_matches: bool
    article_count: int
    chunk_count: int
    replace_article_count: int
    replace_chunk_count: int
    errors: tuple[str, ...]
    token: str | None


@dataclass(frozen=True)
class LegalImportResult:
    source_id: str
    article_count: int
    chunk_count: int
    reused_embeddings: int
    rebuilt_embeddings: int
    embedding_model: str
    embedding_dimension: int
    embedding_signature: str
    first_article_ok: bool
    article_585_ok: bool
    last_article_ok: bool


def _civil_code_spec() -> SourceSpec:
    return next(
        spec for spec in load_manifest(_MANIFEST_PATH)
        if spec.source_id == _CIVIL_CODE_SOURCE_ID
    )


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(raw: str) -> bytes:
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


def _token_key() -> bytes:
    return hashlib.sha256(f"legal-import:{settings.JWT_SECRET}".encode("utf-8")).digest()


def _create_preview_token(*, source_id: str, file_sha256: str, user_id: int) -> str:
    expires_at = datetime.now(timezone.utc) + _TOKEN_TTL
    payload = json.dumps(
        {
            "source_id": source_id,
            "file_sha256": file_sha256,
            "user_id": user_id,
            "expires_at": expires_at.isoformat(),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    encoded = _b64encode(payload)
    signature = hmac.new(_token_key(), encoded.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded}.{_b64encode(signature)}"


def verify_preview_token(
    token: str,
    *,
    raw_content: bytes,
    user_id: int,
    now: datetime | None = None,
) -> dict:
    try:
        encoded, encoded_signature = token.split(".", 1)
        expected = hmac.new(_token_key(), encoded.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64decode(encoded_signature)):
            raise LegalImportError("预检令牌签名无效")
        payload = json.loads(_b64decode(encoded).decode("utf-8"))
    except LegalImportError:
        raise
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LegalImportError("预检令牌格式无效") from exc

    if payload.get("user_id") != user_id:
        raise LegalImportError("预检令牌用户不匹配")
    actual_hash = hashlib.sha256(raw_content).hexdigest()
    if payload.get("file_sha256") != actual_hash:
        raise LegalImportError("预检令牌绑定的文件不匹配")
    try:
        expires_at = datetime.fromisoformat(payload["expires_at"])
    except (KeyError, TypeError, ValueError) as exc:
        raise LegalImportError("预检令牌格式无效") from exc
    if (now or datetime.now(timezone.utc)) >= expires_at:
        raise LegalImportError("预检令牌已过期")
    return payload


def preview_legal_import(
    db: Session,
    *,
    filename: str,
    raw_content: bytes,
    extracted_text: str,
    user_id: int,
) -> LegalImportPreview:
    spec = _civil_code_spec()
    file_sha256 = hashlib.sha256(raw_content).hexdigest()
    candidate = (
        file_sha256 == spec.file_sha256
        or Path(filename).name.casefold() == spec.file.casefold()
        or "民法典" in filename
        or "中华人民共和国民法典" in extracted_text[:500]
    )
    if not candidate:
        return LegalImportPreview(
            candidate=False,
            allowed=False,
            source_id=None,
            title=None,
            file_sha256=file_sha256,
            hash_matches=False,
            article_count=0,
            chunk_count=0,
            replace_article_count=0,
            replace_chunk_count=0,
            errors=(),
            token=None,
        )

    errors: list[str] = []
    articles = ()
    try:
        articles = parse_articles(spec, extracted_text)
        validate_article_set(spec, articles)
    except LegalSourceError as exc:
        errors.append(str(exc))
    hash_matches = hmac.compare_digest(file_sha256, spec.file_sha256)
    if not hash_matches:
        errors.append("文件哈希与官方基准不一致")

    chunks = tuple(
        chunk
        for article in articles
        for chunk in split_legal_article(article, source_title=spec.title)
    )
    article_ids = db.query(LegalArticle.id).filter(LegalArticle.source_id == spec.source_id)
    replace_article_count = db.query(LegalArticle).filter(
        LegalArticle.source_id == spec.source_id
    ).count()
    replace_chunk_count = db.query(KnowledgeChunk).filter(
        KnowledgeChunk.legal_article_id.in_(article_ids)
    ).count()
    allowed = not errors
    token = (
        _create_preview_token(
            source_id=spec.source_id,
            file_sha256=file_sha256,
            user_id=user_id,
        )
        if allowed else None
    )
    return LegalImportPreview(
        candidate=True,
        allowed=allowed,
        source_id=spec.source_id,
        title=spec.title,
        file_sha256=file_sha256,
        hash_matches=hash_matches,
        article_count=len(articles),
        chunk_count=len(chunks),
        replace_article_count=replace_article_count,
        replace_chunk_count=replace_chunk_count,
        errors=tuple(errors),
        token=token,
    )


def apply_legal_import(
    db: Session,
    *,
    filename: str,
    raw_content: bytes,
    extracted_text: str,
    token: str,
    user_id: int,
    commit: bool = True,
) -> LegalImportResult:
    del filename  # 文件名不参与信任判断，内容和令牌才是安全边界。
    payload = verify_preview_token(token, raw_content=raw_content, user_id=user_id)
    spec = _civil_code_spec()
    if payload.get("source_id") != spec.source_id:
        raise LegalImportError("预检令牌法源不匹配")
    if not hmac.compare_digest(hashlib.sha256(raw_content).hexdigest(), spec.file_sha256):
        raise LegalImportError("上传文件不再匹配官方基准")

    articles = parse_articles(spec, extracted_text)
    validate_article_set(spec, articles)
    chunks = [
        {
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
        }
        for article in articles
        for chunk in split_legal_article(article, source_title=spec.title)
    ]
    cache = _embedding_cache(db)
    reused = sum(1 for chunk in chunks if _chunk_cache_key(chunk) in cache)

    # 向量必须在替换事务之前全部生成并通过维度校验。
    rows = retriever.prepare_documents(chunks, embedding_cache=cache)
    db.rollback()
    try:
        old_article_ids = db.query(LegalArticle.id).filter(
            LegalArticle.source_id == spec.source_id
        )
        db.query(KnowledgeChunk).filter(
            KnowledgeChunk.legal_article_id.in_(old_article_ids)
        ).delete(synchronize_session=False)
        db.query(LegalArticle).filter(
            LegalArticle.source_id == spec.source_id
        ).delete(synchronize_session=False)
        db.query(LegalSource).filter(
            LegalSource.source_id == spec.source_id
        ).delete(synchronize_session=False)
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
        for article in articles:
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
        for chunk, row in zip(chunks, rows):
            row.legal_article_id = article_rows[chunk["article_key"]].id
            db.add(row)
        if commit:
            db.commit()
    except Exception:
        db.rollback()
        raise

    article_numbers = {article.article_number for article in articles}
    first_row = rows[0]
    return LegalImportResult(
        source_id=spec.source_id,
        article_count=len(articles),
        chunk_count=len(rows),
        reused_embeddings=reused,
        rebuilt_embeddings=len(rows) - reused,
        embedding_model=first_row.embedding_model or "",
        embedding_dimension=first_row.embedding_dimension or 0,
        embedding_signature=first_row.embedding_signature or "",
        first_article_ok="第一条" in article_numbers,
        article_585_ok="第五百八十五条" in article_numbers,
        last_article_ok="第一千二百六十条" in article_numbers,
    )
