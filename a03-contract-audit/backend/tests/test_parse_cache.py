import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.crypto import encrypt_bytes
from app.db.session import Base
from app.models.models import Contract, ContractParseCache, User
from app.services.parser import cache
from app.services.parser.cache import (
    build_parser_signature,
    deserialize_parse_result,
    get_cached_parse,
    save_parse_cache,
    serialize_parse_result,
)
from app.services.parser.extractor import (
    DocumentBlock,
    DocumentParseResult,
    SourceAnchor,
)


def _parsed(text: str = "第一条 合同正文") -> DocumentParseResult:
    return DocumentParseResult(
        text=text,
        source="mixed",
        ocr_confidence=0.91,
        requires_review=True,
        review_reason="需要人工复核",
        blocks=(
            DocumentBlock(
                block_id="block-1",
                block_type="table_row",
                text="甲方  测试公司",
                anchor=SourceAnchor(
                    page_number=1,
                    bbox=(1.0, 2.0, 30.5, 40.25),
                    table_index=0,
                    row_index=1,
                    char_start=0,
                    char_end=8,
                ),
                cells=("甲方", "测试公司"),
                style="table",
                confidence=0.88,
                parse_source="ocr",
            ),
        ),
        total_pages=2,
        missing_pages=(2,),
    )


def _contract(db: Session, *, content_sha256: str = "a" * 64) -> Contract:
    user = User(
        username=f"cache-user-{content_sha256[:4]}",
        password_hash="x",
        role="legal",
        department="法务部",
    )
    db.add(user)
    db.flush()
    contract = Contract(
        filename="contract.txt",
        storage_path="/contract.txt",
        uploaded_by=user.id,
        department=user.department,
        content_sha256=content_sha256,
    )
    db.add(contract)
    db.flush()
    return contract


def test_parse_result_round_trip_preserves_blocks_and_anchors(monkeypatch):
    monkeypatch.setattr(settings, "FILE_ENCRYPT_KEY", "")
    parsed = _parsed()

    restored = deserialize_parse_result(serialize_parse_result(parsed))

    assert restored == parsed
    assert isinstance(restored.blocks, tuple)
    assert isinstance(restored.blocks[0].cells, tuple)
    assert isinstance(restored.blocks[0].anchor.bbox, tuple)


def test_parse_result_serialization_encrypts_when_key_is_configured(monkeypatch):
    monkeypatch.setattr(settings, "FILE_ENCRYPT_KEY", Fernet.generate_key().decode())

    payload = serialize_parse_result(_parsed("敏感合同正文"))

    assert b"schema" not in payload
    assert "敏感合同正文".encode("utf-8") not in payload
    assert deserialize_parse_result(payload).text == "敏感合同正文"


def test_parse_result_rejects_wrong_key_corruption_and_unknown_schema(monkeypatch):
    first_key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "FILE_ENCRYPT_KEY", first_key)
    encrypted = serialize_parse_result(_parsed())
    monkeypatch.setattr(settings, "FILE_ENCRYPT_KEY", Fernet.generate_key().decode())
    with pytest.raises(ValueError):
        deserialize_parse_result(encrypted)

    monkeypatch.setattr(settings, "FILE_ENCRYPT_KEY", "")
    with pytest.raises(ValueError):
        deserialize_parse_result(b"not-json")
    unknown = encrypt_bytes(json.dumps({"schema": 999, "result": {}}).encode())
    with pytest.raises(ValueError, match="schema"):
        deserialize_parse_result(unknown)


def test_parse_result_rejects_unknown_block_type(monkeypatch):
    monkeypatch.setattr(settings, "FILE_ENCRYPT_KEY", "")
    payload = json.loads(serialize_parse_result(_parsed()).decode("utf-8"))
    payload["result"]["blocks"][0]["block_type"] = "unknown"

    with pytest.raises(ValueError, match="block_type"):
        deserialize_parse_result(json.dumps(payload).encode("utf-8"))


def test_parser_signature_changes_with_code_or_ocr_parameters(monkeypatch):
    baseline = build_parser_signature()

    monkeypatch.setattr(cache, "OCR_MAX_PAGES", cache.OCR_MAX_PAGES + 1)

    assert build_parser_signature() != baseline


def test_cache_lookup_requires_contract_hash_and_parser_signature(monkeypatch):
    monkeypatch.setattr(settings, "FILE_ENCRYPT_KEY", "")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        contract = _contract(db)
        save_parse_cache(db, contract, _parsed())
        db.commit()

        assert get_cached_parse(db, contract) == _parsed()
        contract.content_sha256 = "b" * 64
        assert get_cached_parse(db, contract) is None
        contract.content_sha256 = "a" * 64
        monkeypatch.setattr(cache, "OCR_MAX_PAGES", cache.OCR_MAX_PAGES + 1)
        assert get_cached_parse(db, contract) is None


def test_corrupt_cached_payload_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "FILE_ENCRYPT_KEY", "")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        contract = _contract(db)
        save_parse_cache(db, contract, _parsed())
        db.flush()
        row = db.scalar(select(ContractParseCache))
        row.payload = b"corrupt"
        db.commit()

        assert get_cached_parse(db, contract) is None


def test_concurrent_parse_cache_upserts_keep_one_row(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "FILE_ENCRYPT_KEY", "")
    engine = create_engine(
        f"sqlite:///{tmp_path / 'parse-cache.db'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        contract = _contract(db)
        db.commit()
        contract_id = contract.id

    barrier = threading.Barrier(2)

    def write(text: str) -> None:
        with sessions() as db:
            contract = db.get(Contract, contract_id)
            barrier.wait(timeout=5)
            save_parse_cache(db, contract, _parsed(text))
            db.commit()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(write, text) for text in ("版本一", "版本二")]
        for future in futures:
            future.result(timeout=15)

    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(ContractParseCache)) == 1
        restored = deserialize_parse_result(db.scalar(select(ContractParseCache)).payload)
        assert restored.text in {"版本一", "版本二"}
    engine.dispose()
