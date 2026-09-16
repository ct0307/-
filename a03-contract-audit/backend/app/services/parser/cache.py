"""解析结果的版本化加密缓存。"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict
from importlib import metadata
from pathlib import Path
from typing import Mapping

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import decrypt_bytes, encrypt_bytes
from app.core.logging import get_logger
from app.models.models import Contract, ContractParseCache
from app.services.parser.extractor import (
    DocumentBlock,
    DocumentParseResult,
    SourceAnchor,
)


log = get_logger("parser.cache")

_PARSE_CACHE_SCHEMA = 1
OCR_MAX_PAGES = settings.OCR_MAX_PAGES
OCR_MAX_PAGE_PIXELS = settings.OCR_MAX_PAGE_PIXELS
OCR_DPI = settings.OCR_DPI
OCR_TIMEOUT_SECONDS = settings.OCR_TIMEOUT_SECONDS
OCR_MIN_CONFIDENCE = settings.OCR_MIN_CONFIDENCE

_RESULT_KEYS = {
    "text",
    "source",
    "ocr_confidence",
    "requires_review",
    "review_reason",
    "blocks",
}
_BLOCK_KEYS = {
    "block_id",
    "block_type",
    "text",
    "anchor",
    "cells",
    "style",
    "confidence",
    "parse_source",
}
_ANCHOR_KEYS = {
    "page_number",
    "bbox",
    "paragraph_index",
    "table_index",
    "row_index",
    "char_start",
    "char_end",
}


def serialize_parse_result(parsed: DocumentParseResult) -> bytes:
    if not isinstance(parsed, DocumentParseResult):
        raise TypeError("解析缓存仅接受 DocumentParseResult")
    raw = json.dumps(
        {"schema": _PARSE_CACHE_SCHEMA, "result": asdict(parsed)},
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return encrypt_bytes(raw)


def deserialize_parse_result(payload: bytes) -> DocumentParseResult:
    try:
        raw = decrypt_bytes(payload)
        decoded = json.loads(raw.decode("utf-8"))
    except Exception as error:
        raise ValueError("解析缓存载荷无法解码") from error
    if not isinstance(decoded, dict) or set(decoded) != {"schema", "result"}:
        raise ValueError("解析缓存顶层结构无效")
    if decoded["schema"] != _PARSE_CACHE_SCHEMA:
        raise ValueError("解析缓存 schema 不受支持")
    return _parse_result(decoded["result"])


def build_parser_signature() -> str:
    parser_dir = Path(__file__).resolve().parent
    files = {}
    for filename in ("extractor.py", "ocr.py", "text_decoder.py"):
        files[filename] = hashlib.sha256(
            (parser_dir / filename).read_bytes()
        ).hexdigest()
    versions = {}
    for package in ("pdfplumber", "PyMuPDF", "python-docx", "pytesseract"):
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = "missing"
    identity = {
        "schema": _PARSE_CACHE_SCHEMA,
        "files": files,
        "ocr": {
            "max_pages": OCR_MAX_PAGES,
            "max_page_pixels": OCR_MAX_PAGE_PIXELS,
            "dpi": OCR_DPI,
            "timeout_seconds": OCR_TIMEOUT_SECONDS,
            "min_confidence": OCR_MIN_CONFIDENCE,
        },
        "versions": versions,
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def get_cached_parse(
    db: Session,
    contract: Contract,
) -> DocumentParseResult | None:
    if contract.id is None or not contract.content_sha256:
        return None
    row = db.scalar(select(ContractParseCache).where(
        ContractParseCache.contract_id == contract.id
    ))
    signature = build_parser_signature()
    if (
        row is None
        or row.content_sha256 != contract.content_sha256
        or row.parser_signature != signature
    ):
        return None
    try:
        return deserialize_parse_result(row.payload)
    except Exception as error:
        log.warning(
            "parser.cache_read_failed",
            contract_id=contract.id,
            exception_type=type(error).__name__,
        )
        return None


def save_parse_cache(
    db: Session,
    contract: Contract,
    parsed: DocumentParseResult,
) -> None:
    if contract.id is None or not contract.content_sha256:
        raise ValueError("解析缓存要求已持久化合同和内容哈希")
    values = {
        "contract_id": contract.id,
        "content_sha256": contract.content_sha256,
        "parser_signature": build_parser_signature(),
        "payload": serialize_parse_result(parsed),
    }
    dialect = db.get_bind().dialect.name
    if dialect == "sqlite":
        statement = sqlite_insert(ContractParseCache).values(**values)
        db.execute(statement.on_conflict_do_update(
            index_elements=[ContractParseCache.contract_id],
            set_={
                "content_sha256": statement.excluded.content_sha256,
                "parser_signature": statement.excluded.parser_signature,
                "payload": statement.excluded.payload,
                "updated_at": func.now(),
            },
        ))
        return
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as postgresql_insert

        statement = postgresql_insert(ContractParseCache).values(**values)
        db.execute(statement.on_conflict_do_update(
            index_elements=[ContractParseCache.contract_id],
            set_={
                "content_sha256": statement.excluded.content_sha256,
                "parser_signature": statement.excluded.parser_signature,
                "payload": statement.excluded.payload,
                "updated_at": func.now(),
            },
        ))
        return
    row = db.scalar(select(ContractParseCache).where(
        ContractParseCache.contract_id == contract.id
    ))
    if row is None:
        db.add(ContractParseCache(**values))
        return
    row.content_sha256 = values["content_sha256"]
    row.parser_signature = values["parser_signature"]
    row.payload = values["payload"]


def _parse_result(value: object) -> DocumentParseResult:
    result = _object_with_keys(value, _RESULT_KEYS, "result")
    text = _string(result["text"], "text")
    source = _enum(result["source"], {"native", "ocr", "mixed"}, "source")
    confidence = _optional_number(result["ocr_confidence"], "ocr_confidence")
    requires_review = result["requires_review"]
    if not isinstance(requires_review, bool):
        raise ValueError("requires_review 类型无效")
    review_reason = _optional_string(result["review_reason"], "review_reason")
    blocks_raw = result["blocks"]
    if not isinstance(blocks_raw, list):
        raise ValueError("blocks 类型无效")
    return DocumentParseResult(
        text=text,
        source=source,
        ocr_confidence=confidence,
        requires_review=requires_review,
        review_reason=review_reason,
        blocks=tuple(_parse_block(item) for item in blocks_raw),
    )


def _parse_block(value: object) -> DocumentBlock:
    block = _object_with_keys(value, _BLOCK_KEYS, "block")
    cells = block["cells"]
    if not isinstance(cells, list) or any(not isinstance(item, str) for item in cells):
        raise ValueError("cells 类型无效")
    return DocumentBlock(
        block_id=_string(block["block_id"], "block_id"),
        block_type=_enum(
            block["block_type"],
            {"paragraph", "table_row", "page_text"},
            "block_type",
        ),
        text=_string(block["text"], "block.text"),
        anchor=_parse_anchor(block["anchor"]),
        cells=tuple(cells),
        style=_string(block["style"], "style"),
        confidence=_optional_number(block["confidence"], "confidence"),
        parse_source=_enum(
            block["parse_source"], {"native", "ocr"}, "parse_source"
        ),
    )


def _parse_anchor(value: object) -> SourceAnchor:
    anchor = _object_with_keys(value, _ANCHOR_KEYS, "anchor")
    bbox_raw = anchor["bbox"]
    bbox = None
    if bbox_raw is not None:
        if not isinstance(bbox_raw, list) or len(bbox_raw) != 4:
            raise ValueError("bbox 类型无效")
        bbox = tuple(_number(item, "bbox") for item in bbox_raw)
    return SourceAnchor(
        page_number=_optional_int(anchor["page_number"], "page_number"),
        bbox=bbox,
        paragraph_index=_optional_int(
            anchor["paragraph_index"], "paragraph_index"
        ),
        table_index=_optional_int(anchor["table_index"], "table_index"),
        row_index=_optional_int(anchor["row_index"], "row_index"),
        char_start=_optional_int(anchor["char_start"], "char_start"),
        char_end=_optional_int(anchor["char_end"], "char_end"),
    )


def _object_with_keys(
    value: object,
    keys: set[str],
    field: str,
) -> Mapping[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{field} 字段无效")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} 类型无效")
    return value


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _string(value, field)


def _enum(value: object, allowed: set[str], field: str) -> str:
    result = _string(value, field)
    if result not in allowed:
        raise ValueError(f"{field} 值无效")
    return result


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} 类型无效")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} 数值无效")
    return result


def _optional_number(value: object, field: str) -> float | None:
    if value is None:
        return None
    return _number(value, field)


def _optional_int(value: object, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} 类型无效")
    return value
