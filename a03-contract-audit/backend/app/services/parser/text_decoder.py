from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Literal


TextEncoding = Literal["utf-8-sig", "utf-8", "gb18030"]
TextDecodeErrorCode = Literal["TEXT_ENCODING_ERROR", "TEXT_EMPTY"]


@dataclass(frozen=True)
class DecodedText:
    text: str
    encoding: TextEncoding


class TextDecodeError(ValueError):
    def __init__(self, code: TextDecodeErrorCode) -> None:
        self.code = code
        super().__init__(code)


def decode_text_bytes(content: bytes) -> DecodedText:
    if not content or b"\x00" in content:
        raise TextDecodeError("TEXT_ENCODING_ERROR")

    encodings: tuple[TextEncoding, ...] = (
        ("utf-8-sig",)
        if content.startswith(b"\xef\xbb\xbf")
        else ("utf-8", "gb18030")
    )
    candidates: list[DecodedText] = []
    for encoding in encodings:
        try:
            candidates.append(
                DecodedText(content.decode(encoding, errors="strict"), encoding)
            )
        except UnicodeDecodeError:
            continue

    if not candidates:
        raise TextDecodeError("TEXT_ENCODING_ERROR")

    chosen = max(candidates, key=_text_quality_key)
    if not any(char.isprintable() and not char.isspace() for char in chosen.text):
        raise TextDecodeError("TEXT_EMPTY")
    return chosen


def _text_quality_key(candidate: DecodedText) -> tuple[int, float, float, int]:
    text = candidate.text
    non_whitespace = tuple(char for char in text if not char.isspace())
    length = len(non_whitespace)
    control_count = sum(
        1 for char in text if unicodedata.category(char).startswith("C")
    )
    printable_ratio = (
        sum(char.isprintable() for char in non_whitespace) / length if length else 0.0
    )
    cjk_ratio = (
        sum(_is_cjk(char) for char in non_whitespace) / length if length else 0.0
    )
    utf8_preference = int(candidate.encoding in {"utf-8", "utf-8-sig"})
    return (-control_count, printable_ratio, cjk_ratio, utf8_preference)


def _is_cjk(char: str) -> bool:
    return (
        "\u3400" <= char <= "\u4dbf"
        or "\u4e00" <= char <= "\u9fff"
        or "\uf900" <= char <= "\ufaff"
    )
