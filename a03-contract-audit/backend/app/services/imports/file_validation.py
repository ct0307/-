"""导入前的文件内容预检。"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import lzma
import os
import re
import struct
import zlib
from zipfile import BadZipFile, LargeZipFile, ZipFile, ZipInfo

import fitz

from app.services.parser.text_decoder import TextDecodeError, decode_text_bytes


_ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
_ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
# 同步预检资源边界，避免上传请求解压异常归档。
MAX_DOCX_MEMBER_COUNT = 4096
MAX_DOCX_TOTAL_UNCOMPRESSED_SIZE = 128 * 1024 * 1024
MAX_DOCX_LARGE_MEMBER_SIZE = 8 * 1024 * 1024
MAX_DOCX_COMPRESSION_RATIO = 200
_DOCX_RESOURCE_LIMIT_MESSAGE = "DOCX 压缩结构超过安全限制"
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

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        self.message = message or _ERROR_MESSAGES[code]
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
            members = archive.infolist()
            _validate_docx_structure(members)
            if archive.testzip() is not None:
                raise FileValidationError("DOCX_CORRUPT")
    except FileValidationError:
        raise
    except (
        BadZipFile,
        LargeZipFile,
        OSError,
        RuntimeError,
        UnicodeDecodeError,
        EOFError,
        lzma.LZMAError,
        NotImplementedError,
        struct.error,
        zlib.error,
    ) as error:
        raise FileValidationError("DOCX_CORRUPT") from error


def _validate_docx_structure(members: list[ZipInfo]) -> None:
    if any(_is_unsafe_zip_path(member.orig_filename) for member in members):
        raise FileValidationError("DOCX_STRUCTURE_INVALID")
    names = {member.filename for member in members}
    if "[Content_Types].xml" not in names or "word/document.xml" not in names:
        raise FileValidationError("DOCX_STRUCTURE_INVALID")
    if len(members) > MAX_DOCX_MEMBER_COUNT:
        _raise_docx_resource_limit()

    total_uncompressed_size = sum(member.file_size for member in members)
    if total_uncompressed_size > MAX_DOCX_TOTAL_UNCOMPRESSED_SIZE:
        _raise_docx_resource_limit()
    for member in members:
        compression_ratio = member.file_size / max(member.compress_size, 1)
        if (
            member.file_size > MAX_DOCX_LARGE_MEMBER_SIZE
            and compression_ratio > MAX_DOCX_COMPRESSION_RATIO
        ):
            _raise_docx_resource_limit()


def _raise_docx_resource_limit() -> None:
    raise FileValidationError("DOCX_STRUCTURE_INVALID", _DOCX_RESOURCE_LIMIT_MESSAGE)


def _is_unsafe_zip_path(name: str) -> bool:
    if name.startswith("/") or "\\" in name or re.match(r"^[A-Za-z]:", name):
        return True
    return ".." in name.split("/")


def _validate_text(content: bytes) -> str:
    try:
        return decode_text_bytes(content).encoding
    except TextDecodeError as error:
        raise FileValidationError(error.code) from error
