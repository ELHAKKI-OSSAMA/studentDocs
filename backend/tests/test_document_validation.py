"""Upload validation (pure): magic bytes, extension / declared type consistency, names, size, SHA-256."""

import hashlib

import pytest

from app.core.errors import AppError
from app.documents.scanner import ClamdScanner, ScannerError
from app.documents.validation import safe_filename, validate_upload
from tests.factories import EXE, PDF, PNG

JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 32
MAX = 1024


def code(exc: pytest.ExceptionInfo) -> str:
    return exc.value.code


def test_valid_file_metadata_comes_from_the_content():
    file = validate_upload("Relevé de notes.PDF", PDF, MAX, "application/pdf")
    assert file.mime_type == "application/pdf"
    assert file.size == len(PDF)
    assert file.sha256 == hashlib.sha256(PDF).hexdigest()
    assert file.filename == "Relevé_de_notes.pdf"
    assert file.original_filename == "Relevé de notes.PDF"
    assert file.file.read() == PDF


@pytest.mark.parametrize(
    ("name", "data", "declared"),
    [
        ("scan.png", PNG, "image/png"),
        ("photo.jpg", JPEG, "image/jpeg"),
        ("photo.jpeg", JPEG, "image/jpg"),  # common alias
        ("doc.pdf", PDF, ""),  # no declared type
        ("doc.pdf", PDF, "application/octet-stream"),  # generic declared type
        ("doc.pdf", PDF, "application/pdf; charset=binary"),
    ],
)
def test_accepted_combinations(name, data, declared):
    assert validate_upload(name, data, MAX, declared).size == len(data)


@pytest.mark.parametrize(
    ("name", "data", "declared", "expected"),
    [
        # An executable renamed to look like a PDF: refused on its content.
        ("document.pdf", EXE, "application/pdf", "file_type_not_allowed"),
        ("malware.exe", EXE, "application/x-msdownload", "file_type_not_allowed"),
        (
            "page.pdf",
            b"<html><script>alert(1)</script>",
            "application/pdf",
            "file_type_not_allowed",
        ),
        # Real PDF content but a misleading extension or declared type.
        ("photo.png", PDF, "", "file_extension_mismatch"),
        ("document", PDF, "", "file_extension_mismatch"),
        ("doc.pdf", PDF, "image/png", "file_mime_mismatch"),
        ("image.png", PNG, "application/pdf", "file_mime_mismatch"),
        # Dangerous double extensions, whatever the content.
        ("facture.exe.pdf", PDF, "application/pdf", "file_name_not_allowed"),
        ("cv.js.pdf", PDF, "", "file_name_not_allowed"),
        ("image.svg.png", PNG, "", "file_name_not_allowed"),
        # Size.
        ("empty.pdf", b"", "", "file_empty"),
        ("big.pdf", PDF + b"0" * MAX, "", "file_too_large"),
    ],
)
def test_rejections(name, data, declared, expected):
    with pytest.raises(AppError) as exc:
        validate_upload(name, data, MAX, declared)
    assert code(exc) == expected


@pytest.mark.parametrize(
    ("original", "expected"),
    [
        ("../../etc/passwd.pdf", "passwd.pdf"),
        ("C:\\Users\\x\\secret.pdf", "secret.pdf"),
        ("rapport\u202egnp.pdf", "rapportgnp.pdf"),  # right-to-left override removed
        ("a\x00b\r\nc.pdf", "abc.pdf"),  # control characters removed
        ('"; rm -rf / ;".pdf', "document.pdf"),  # only the part after the last / is kept
        ("شهادة التمدرس.pdf", "شهادة_التمدرس.pdf"),  # non-Latin names are kept
        ("..pdf", "document.pdf"),
        ("x" * 300 + ".pdf", "x" * 100 + ".pdf"),
    ],
)
def test_dangerous_and_special_names_are_normalized(original, expected):
    assert safe_filename(original, ".pdf") == expected


def test_original_name_never_contains_a_path_or_controls():
    file = validate_upload("../../a\u202eb\x07.pdf", PDF, MAX)
    assert file.original_filename == "ab.pdf"


@pytest.mark.parametrize(
    ("reply", "infected", "signature"),
    [
        ("stream: OK", False, None),
        ("stream: Eicar-Test-Signature FOUND", True, "Eicar-Test-Signature"),
        ("stream: Win.Test.EICAR_HDB-1 FOUND", True, "Win.Test.EICAR_HDB-1"),
    ],
)
def test_clamd_replies(reply, infected, signature):
    result = ClamdScanner.parse_reply(reply)
    assert result.infected is infected and result.signature == signature


@pytest.mark.parametrize("reply", ["INSTREAM size limit exceeded. ERROR", "", "stream: garbage"])
def test_unexpected_clamd_replies_are_errors_never_clean(reply):
    with pytest.raises(ScannerError):
        ClamdScanner.parse_reply(reply)
