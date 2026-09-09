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
from app.models.models import KnowledgeChunk, LegalArticle
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
    candidate = "民法典" in filename or "中华人民共和国民法典" in extracted_text[:500]
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
