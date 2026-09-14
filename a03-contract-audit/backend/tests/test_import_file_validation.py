from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

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


def _validation_error(filename: str, content: bytes) -> FileValidationError:
    with pytest.raises(FileValidationError) as raised:
        validate_upload(filename, content)
    return raised.value


def test_accepts_valid_pdf_and_closes_document():
    result = validate_upload("CONTRACT.PDF", _valid_pdf_bytes())

    assert result.extension == ".pdf"
    assert result.text_encoding is None


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
