from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

import fitz
import pytest

from app.services.imports import file_validation
from app.services.imports.file_validation import FileValidationError, validate_upload


def _valid_pdf_bytes() -> bytes:
    document = fitz.open()
    document.new_page()
    content = document.tobytes()
    document.close()
    return content


def _docx_bytes(*, names: tuple[str, ...] = ("[Content_Types].xml", "word/document.xml")) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_STORED) as archive:
        for name in names:
            archive.writestr(name, "<xml />")
    return output.getvalue()


def _docx_bytes_with_corrupt_deflated_member() -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<xml />")
        archive.writestr("word/document.xml", b"contract body" * 200)

    content = bytearray(output.getvalue())
    with ZipFile(BytesIO(content)) as archive:
        member = archive.getinfo("word/document.xml")
    data_offset = member.header_offset + 30 + len(member.orig_filename) + len(member.extra)
    content[data_offset] ^= 0xFF
    return bytes(content)


def _docx_bytes_with_invalid_utf8_member_name() -> bytes:
    output = BytesIO()
    member_name = "\u4e2d.xml"
    with ZipFile(output, "w", ZIP_STORED) as archive:
        archive.writestr("[Content_Types].xml", "<xml />")
        archive.writestr("word/document.xml", "<xml />")
        archive.writestr(member_name, "<xml />")

    content = bytearray(output.getvalue())
    name_offset = content.rfind(member_name.encode("utf-8"))
    content[name_offset] = 0xFF
    return bytes(content)


def _docx_bytes_with_highly_compressed_member() -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<xml />")
        archive.writestr("word/document.xml", "<xml />")
        archive.writestr("unrelated.bin", b"x" * (16 * 1024 * 1024))
    return output.getvalue()


def _replace_zipfile_with_members(monkeypatch, members: list[ZipInfo]):
    class FakeZipFile:
        testzip_called = False

        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            pass

        def infolist(self) -> list[ZipInfo]:
            return members

        def testzip(self):
            self.testzip_called = True
            pytest.fail("资源边界拒绝前不应执行 CRC 校验")

    monkeypatch.setattr(file_validation, "ZipFile", FakeZipFile)
    return FakeZipFile


def _validation_error(filename: str, content: bytes) -> FileValidationError:
    with pytest.raises(FileValidationError) as raised:
        validate_upload(filename, content)
    return raised.value


def test_accepts_valid_pdf_and_closes_document(monkeypatch):
    content = _valid_pdf_bytes()
    original_open = fitz.open
    opened_documents = []

    class TrackingDocument:
        def __init__(self, document) -> None:
            self._document = document
            self.closed = False

        def __getattr__(self, name):
            return getattr(self._document, name)

        def __len__(self) -> int:
            return len(self._document)

        def close(self) -> None:
            self.closed = True
            self._document.close()

    def open_document(**kwargs):
        document = TrackingDocument(original_open(**kwargs))
        opened_documents.append(document)
        return document

    monkeypatch.setattr(file_validation.fitz, "open", open_document)

    result = validate_upload("CONTRACT.PDF", content)

    assert result.extension == ".pdf"
    assert result.text_encoding is None
    assert opened_documents[0].closed is True


def test_rejects_nonempty_corrupt_pdf_without_exposing_content():
    secret = b"confidential-contract-body"
    error = _validation_error("contract.pdf", b"%PDF-not-a-real-file" + secret)

    assert error.code == "PDF_CORRUPT"
    assert error.message
    assert secret.decode() not in str(error)


def test_rejects_docx_content_masquerading_as_pdf():
    error = _validation_error("contract.pdf", _docx_bytes())

    assert error.code == "FILE_TYPE_MISMATCH"


def test_rejects_encrypted_pdf(monkeypatch):
    class FakeDocument:
        needs_pass = True
        closed = False

        def __len__(self) -> int:
            return 1

        def close(self) -> None:
            self.closed = True

    document = FakeDocument()
    monkeypatch.setattr(file_validation.fitz, "open", lambda **_kwargs: document)

    error = _validation_error("contract.pdf", b"%PDF-1.7")

    assert error.code == "PDF_ENCRYPTED"
    assert document.closed is True


def test_rejects_zero_page_pdf_and_closes_document(monkeypatch):
    class FakeDocument:
        needs_pass = False
        closed = False

        def __len__(self) -> int:
            return 0

        def close(self) -> None:
            self.closed = True

    document = FakeDocument()
    monkeypatch.setattr(file_validation.fitz, "open", lambda **_kwargs: document)

    error = _validation_error("contract.pdf", b"%PDF-1.7")

    assert error.code == "PDF_EMPTY"
    assert document.closed is True


def test_rejects_pdf_when_open_fails(monkeypatch):
    monkeypatch.setattr(
        file_validation.fitz,
        "open",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("bad pdf")),
    )

    assert _validation_error("contract.pdf", b"%PDF-1.7").code == "PDF_CORRUPT"


def test_accepts_valid_docx():
    result = validate_upload("contract.docx", _docx_bytes())

    assert result.extension == ".docx"
    assert result.text_encoding is None


def test_rejects_docx_missing_document_part():
    error = _validation_error("contract.docx", _docx_bytes(names=("[Content_Types].xml",)))

    assert error.code == "DOCX_STRUCTURE_INVALID"


@pytest.mark.parametrize("member_name", ("../word/document.xml", "word\\document.xml", "C:/word/document.xml", "/word/document.xml"))
def test_rejects_unsafe_docx_member_path(member_name: str):
    if "\\" in member_name:
        content = _docx_bytes(
            names=("[Content_Types].xml", "word/document.xml", "evil/path.xml")
        ).replace(b"evil/path.xml", b"evil\\path.xml")
    else:
        content = _docx_bytes(
            names=("[Content_Types].xml", "word/document.xml", member_name)
        )
    error = _validation_error(
        "contract.docx",
        content,
    )

    assert error.code == "DOCX_STRUCTURE_INVALID"


def test_empty_zip_is_a_structure_error_not_type_mismatch():
    output = BytesIO()
    with ZipFile(output, "w"):
        pass

    assert _validation_error("contract.docx", output.getvalue()).code == "DOCX_STRUCTURE_INVALID"


def test_rejects_docx_with_corrupt_zip_member():
    content = bytearray(_docx_bytes())
    offset = content.index(b"<xml />")
    content[offset] = ord("X")

    assert _validation_error("contract.docx", bytes(content)).code == "DOCX_CORRUPT"


def test_rejects_docx_when_deflate_member_raises_zlib_error():
    error = _validation_error("contract.docx", _docx_bytes_with_corrupt_deflated_member())

    assert error.code == "DOCX_CORRUPT"


def test_rejects_docx_with_invalid_utf8_member_metadata():
    error = _validation_error("contract.docx", _docx_bytes_with_invalid_utf8_member_name())

    assert error.code == "DOCX_CORRUPT"


def test_rejects_highly_compressed_docx_member_before_crc(monkeypatch):
    content = _docx_bytes_with_highly_compressed_member()
    with ZipFile(BytesIO(content)) as archive:
        member = archive.getinfo("unrelated.bin")
    assert member.file_size == 16 * 1024 * 1024
    assert member.file_size / member.compress_size > 200

    monkeypatch.setattr(
        file_validation.ZipFile,
        "testzip",
        lambda _archive: pytest.fail("资源边界拒绝前不应执行 CRC 校验"),
    )

    error = _validation_error("contract.docx", content)

    assert error.code == "DOCX_STRUCTURE_INVALID"
    assert error.message == "DOCX 压缩结构超过安全限制"


def test_rejects_docx_with_too_many_members_before_crc(monkeypatch):
    members = [ZipInfo(f"extra/{index}") for index in range(4097)]
    members[0] = ZipInfo("[Content_Types].xml")
    members[1] = ZipInfo("word/document.xml")
    fake_zipfile = _replace_zipfile_with_members(monkeypatch, members)

    error = _validation_error("contract.docx", b"PK\x03\x04")

    assert error.code == "DOCX_STRUCTURE_INVALID"
    assert fake_zipfile.testzip_called is False


def test_rejects_docx_over_total_uncompressed_size_before_crc(monkeypatch):
    content_types = ZipInfo("[Content_Types].xml")
    content_types.file_size = 64 * 1024 * 1024 + 1
    content_types.compress_size = content_types.file_size
    document = ZipInfo("word/document.xml")
    document.file_size = 64 * 1024 * 1024 + 1
    document.compress_size = document.file_size
    fake_zipfile = _replace_zipfile_with_members(monkeypatch, [content_types, document])

    error = _validation_error("contract.docx", b"PK\x03\x04")

    assert error.code == "DOCX_STRUCTURE_INVALID"
    assert fake_zipfile.testzip_called is False


@pytest.mark.parametrize("filename", ("contract.exe", "contract", ".hidden"))
def test_rejects_unsupported_extension(filename: str):
    assert _validation_error(filename, b"content").code == "UNSUPPORTED_FILE_TYPE"


def test_rejects_empty_content_before_type_parsing():
    assert _validation_error("contract.pdf", b"").code == "EMPTY_FILE"


def test_accepts_utf8_bom_text_and_returns_encoding():
    result = validate_upload("contract.txt", "\ufeff合同正文".encode("utf-8"))

    assert result.extension == ".txt"
    assert result.text_encoding == "utf-8-sig"


def test_accepts_gb18030_text_and_returns_encoding():
    result = validate_upload("contract.txt", "合同正文".encode("gb18030"))

    assert result.text_encoding == "gb18030"


def test_rejects_text_with_nul_byte():
    assert _validation_error("contract.txt", b"contract\x00body").code == "TEXT_ENCODING_ERROR"


def test_rejects_text_with_unsupported_encoding():
    content = b"\x81"

    assert b"\x00" not in content
    assert _validation_error("contract.txt", content).code == "TEXT_ENCODING_ERROR"


@pytest.mark.parametrize("content", (b" \n\t", "\u200b\u200b".encode("utf-8")))
def test_rejects_whitespace_or_non_printable_text(content: bytes):
    assert _validation_error("contract.txt", content).code == "TEXT_EMPTY"
