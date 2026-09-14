"""导入前的文件内容预检。"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import os
import re
import zlib
from zipfile import BadZipFile, ZipFile

import fitz


_ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
_ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_ERROR_MESSAGES = {
    "UNSUPPORTED_FILE_TYPE": "不支持的文件类型",
    "EMPTY_FILE": "文件内容为空",
    "FILE_TYPE_MISMATCH": "文件扩展名与内容不匹配",
    "PDF_CORRUPT": "PDF 文件损坏或无法打开",
    "PDF_EMPTY": "PDF 不包含页面",
    "PDF_ENCRYPTED": "PDF 已加密",
    "DOCX_CORRUPT": "DOCX 文件损坏",
    "DOCX_STRUCTURE_INVALID": "DOCX 文件结构无效",
    "TEXT_ENCODING_ERROR": "文本编码无效",
    "TEXT_EMPTY": "文本不含有效内容",
}


@dataclass(frozen=True)
class ValidatedUpload:
    extension: str
    text_encoding: str | None = None


class FileValidationError(ValueError):
    """不含上传正文的稳定预检异常。"""

    def __init__(self, code: str) -> None:
        self.code = code
        self.message = _ERROR_MESSAGES[code]
        super().__init__(self.message)


def validate_upload(filename: str, content: bytes) -> ValidatedUpload:
    """验证上传文件的扩展名与基础内容完整性。"""
    extension = os.path.splitext(os.path.basename(filename))[1].lower()
    if extension not in _ALLOWED_EXTENSIONS:
        raise FileValidationError("UNSUPPORTED_FILE_TYPE")
    if not content:
        raise FileValidationError("EMPTY_FILE")

    if extension == ".pdf":
        _validate_pdf(content)
        return ValidatedUpload(extension=extension)
    if extension == ".docx":
        _validate_docx(content)
        return ValidatedUpload(extension=extension)

    return ValidatedUpload(extension=extension, text_encoding=_validate_text(content))


def _validate_pdf(content: bytes) -> None:
    if not content.startswith(b"%PDF-"):
        raise FileValidationError("FILE_TYPE_MISMATCH")

    document = None
    try:
        document = fitz.open(stream=content, filetype="pdf")
        if document.needs_pass:
            raise FileValidationError("PDF_ENCRYPTED")
        if len(document) < 1:
            raise FileValidationError("PDF_EMPTY")
    except FileValidationError:
        raise
    except Exception as error:
        raise FileValidationError("PDF_CORRUPT") from error
    finally:
        if document is not None:
            try:
                document.close()
            except Exception:
                pass


def _validate_docx(content: bytes) -> None:
    if not content.startswith(_ZIP_SIGNATURES):
        raise FileValidationError("FILE_TYPE_MISMATCH")

    try:
        with ZipFile(BytesIO(content)) as archive:
            if archive.testzip() is not None:
                raise FileValidationError("DOCX_CORRUPT")
            members = archive.infolist()
    except FileValidationError:
        raise
    except (BadZipFile, OSError, RuntimeError, zlib.error) as error:
        raise FileValidationError("DOCX_CORRUPT") from error

    if any(_is_unsafe_zip_path(member.orig_filename) for member in members):
        raise FileValidationError("DOCX_STRUCTURE_INVALID")
    names = {member.filename for member in members}
    if "[Content_Types].xml" not in names or "word/document.xml" not in names:
        raise FileValidationError("DOCX_STRUCTURE_INVALID")


def _is_unsafe_zip_path(name: str) -> bool:
    if name.startswith("/") or "\\" in name or re.match(r"^[A-Za-z]:", name):
        return True
    return ".." in name.split("/")


def _validate_text(content: bytes) -> str:
    if b"\x00" in content:
        raise FileValidationError("TEXT_ENCODING_ERROR")

    for encoding in ("utf-8-sig", "gb18030"):
        try:
            text = content.decode(encoding, errors="strict")
            break
        except UnicodeDecodeError:
            continue
    else:
        raise FileValidationError("TEXT_ENCODING_ERROR")

    if not text.strip() or not any(char.isprintable() and not char.isspace() for char in text):
        raise FileValidationError("TEXT_EMPTY")
    return encoding
