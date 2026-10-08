"""Upload validation: size, real content type (magic bytes) and a safe display filename."""

import hashlib
import re
import unicodedata
from dataclasses import dataclass

from app.core.errors import AppError

# Accepted formats, identified by content, never by the client-provided name or MIME type.
SIGNATURES: tuple[tuple[str, bytes, str], ...] = (
    ("application/pdf", b"%PDF-", ".pdf"),
    ("image/png", b"\x89PNG\r\n\x1a\n", ".png"),
    ("image/jpeg", b"\xff\xd8\xff", ".jpg"),
)
ALLOWED_MIME_TYPES = tuple(m for m, _, _ in SIGNATURES)
_UNSAFE_CHARS = re.compile(r"[^\w.\- ]+", re.UNICODE)


@dataclass(frozen=True)
class ValidatedFile:
    filename: str
    mime_type: str
    data: bytes
    sha256: str

    @property
    def size(self) -> int:
        return len(self.data)


def sniff_mime(data: bytes) -> tuple[str, str] | None:
    for mime, magic, ext in SIGNATURES:
        if data.startswith(magic):
            return mime, ext
    return None


def safe_filename(original: str | None, extension: str) -> str:
    """Display name only (storage keys are random). Strips paths, control chars and odd symbols."""
    name = (original or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = unicodedata.normalize("NFKC", name)
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C")
    stem = name.rsplit(".", 1)[0] if "." in name else name
    stem = _UNSAFE_CHARS.sub("_", stem)
    stem = re.sub(r"[_\s.]+", "_", stem).strip("_-. ")[:100]
    return f"{stem or 'document'}{extension}"


def validate_upload(original_name: str | None, data: bytes, max_bytes: int) -> ValidatedFile:
    if not data:
        raise AppError.of(422, "file_empty", "The file is empty", {"filename": original_name})
    if len(data) > max_bytes:
        raise AppError.of(
            422,
            "file_too_large",
            "The file is too large",
            {"filename": original_name, "max_bytes": max_bytes},
        )
    sniffed = sniff_mime(data)
    if sniffed is None:
        raise AppError.of(
            422,
            "file_type_not_allowed",
            "Only PDF, PNG and JPEG files are accepted",
            {"filename": original_name, "allowed": list(ALLOWED_MIME_TYPES)},
        )
    mime, ext = sniffed
    return ValidatedFile(
        filename=safe_filename(original_name, ext),
        mime_type=mime,
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
    )
