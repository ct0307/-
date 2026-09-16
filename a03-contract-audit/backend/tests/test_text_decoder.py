from __future__ import annotations

import pytest

from app.services.parser.extractor import extract_document
from app.services.parser.text_decoder import TextDecodeError, decode_text_bytes


def test_gb18030_round_trips_without_character_loss():
    source = "合同类型：采购合同\n甲方向乙方采购设备。"

    decoded = decode_text_bytes(source.encode("gb18030"))

    assert decoded.text == source
    assert decoded.encoding == "gb18030"


def test_utf8_round_trips_without_character_loss():
    source = "合同类型：服务合同\n服务内容完整。"

    decoded = decode_text_bytes(source.encode("utf-8"))

    assert decoded.text == source
    assert decoded.encoding == "utf-8"


@pytest.mark.parametrize(
    ("content", "error_code"),
    [
        (b"\x00\xff\xfe", "TEXT_ENCODING_ERROR"),
        (b"\x81", "TEXT_ENCODING_ERROR"),
        (b" \r\n\t", "TEXT_EMPTY"),
        ("\u200b\u200b".encode("utf-8"), "TEXT_EMPTY"),
    ],
)
def test_invalid_or_empty_text_uses_stable_error_codes(content: bytes, error_code: str):
    with pytest.raises(TextDecodeError, match=error_code) as raised:
        decode_text_bytes(content)

    assert raised.value.code == error_code


def test_txt_extraction_uses_the_shared_strict_decoder(tmp_path):
    source = "合同类型：采购合同\n甲方向乙方采购设备。"
    file_path = tmp_path / "contract.txt"
    file_path.write_bytes(source.encode("gb18030"))

    result = extract_document(str(file_path))

    assert result.text == source
    assert result.source == "native"
