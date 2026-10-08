"""Upload validation, done before anything is stored.

Nothing sent by the client is trusted: the type is detected from the content (magic bytes) and must
agree with the file extension and, when one is sent, the declared MIME type. The content is copied in
chunks into a spooled temporary file while its SHA-256 is computed (bounded memory, bounded size).
"""

import hashlib
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from typing import BinaryIO

from app.core.errors import AppError

CHUNK_SIZE = 64 * 1024
# Files up to this size stay in memory; larger ones spill to a temporary file.
SPOOL_MAX_MEMORY = 1024 * 1024

# Accepted formats: detected MIME type, magic bytes, canonical extension, accepted extensions.
SIGNATURES: tuple[tuple[str, bytes, str, frozenset[str]], ...] = (
    ("application/pdf", b"%PDF-", ".pdf", frozenset({".pdf"})),
    ("image/png", b"\x89PNG\r\n\x1a\n", ".png", frozenset({".png"})),
    ("image/jpeg", b"\xff\xd8\xff", ".jpg", frozenset({".jpg", ".jpeg"})),
)
ALLOWED_MIME_TYPES = tuple(m for m, _, _, _ in SIGNATURES)
# Declared types that carry no information (curl, some browsers) and aliases of the accepted ones.
NEUTRAL_DECLARED_TYPES = frozenset({"", "application/octet-stream", "binary/octet-stream"})
MIME_ALIASES = {
    "image/jpg": "image/jpeg",
    "image/pjpeg": "image/jpeg",
    "application/x-pdf": "application/pdf",
}
# Executable / script extensions are refused anywhere in the name ("facture.exe.pdf").
DANGEROUS_EXTENSIONS = frozenset(
    {
        "exe", "dll", "com", "scr", "msi", "msp", "bat", "cmd", "ps1", "psm1", "vbs", "vbe", "js", "jse",
        "wsf", "wsh", "hta", "jar", "sh", "bash", "php", "phtml", "py", "pl", "cgi", "app", "apk", "lnk",
        "reg", "cpl", "iso", "dmg", "html", "htm", "svg", "xhtml",
    }
)  # fmt: skip
_UNSAFE_CHARS = re.compile(r"[^\w.\- ]+", re.UNICODE)


@dataclass
class ValidatedFile:
    filename: str  # normalized display name
    original_filename: str  # as uploaded, control characters removed (audit / display to staff only)
    mime_type: str  # detected from the content
    size: int
    sha256: str
    file: BinaryIO  # positioned at 0, closed by the owner

    def close(self) -> None:
        self.file.close()


def sniff_mime(data: bytes) -> tuple[str, str] | None:
    for mime, magic, ext, _ in SIGNATURES:
        if data.startswith(magic):
            return mime, ext
    return None


def _strip_controls(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return "".join(ch for ch in text if unicodedata.category(ch)[0] != "C")


def original_name(original: str | None) -> str:
    """Basename as uploaded, without path or control characters (never used as a storage key)."""
    name = (original or "").replace("\\", "/").rsplit("/", 1)[-1]
    return _strip_controls(name).strip()[:255]


def safe_filename(original: str | None, extension: str) -> str:
    """Display name only (storage keys are random). Strips paths, control chars and odd symbols."""
    name = original_name(original)
    stem = name.rsplit(".", 1)[0] if "." in name else name
    stem = _UNSAFE_CHARS.sub("_", stem)
    stem = re.sub(r"[_\s.]+", "_", stem).strip("_-. ")[:100]
    return f"{stem or 'document'}{extension}"


def _reject(code: str, message: str, filename: str | None, **details) -> AppError:
    return AppError.of(422, code, message, {"filename": filename, **details})


def check_name(name: str, mime: str) -> None:
    parts = name.lower().split(".")
    extension = f".{parts[-1]}" if len(parts) > 1 else ""
    if any(part.strip() in DANGEROUS_EXTENSIONS for part in parts[1:]):
        raise _reject("file_name_not_allowed", "This file name is not allowed", name)
    accepted = next(exts for m, _, _, exts in SIGNATURES if m == mime)
    if extension not in accepted:
        raise _reject(
            "file_extension_mismatch",
            "The file extension does not match its content",
            name,
            detected=mime,
        )


def check_declared_type(declared: str | None, detected: str, name: str) -> None:
    value = (declared or "").split(";", 1)[0].strip().lower()
    value = MIME_ALIASES.get(value, value)
    if value not in NEUTRAL_DECLARED_TYPES and value != detected:
        raise _reject(
            "file_mime_mismatch",
            "The declared file type does not match its content",
            name,
            detected=detected,
        )


def validate_stream(
    original: str | None, stream: BinaryIO, max_bytes: int, declared_type: str | None = None
) -> ValidatedFile:
    """Copies `stream` into a spooled temporary file while hashing it, then validates the content."""
    name = original_name(original)
    digest = hashlib.sha256()
    spool = tempfile.SpooledTemporaryFile(max_size=SPOOL_MAX_MEMORY)  # noqa: SIM115 - owned by the result
    size = 0
    head = b""
    try:
        while chunk := stream.read(CHUNK_SIZE):
            size += len(chunk)
            if size > max_bytes:
                raise _reject("file_too_large", "The file is too large", name, max_bytes=max_bytes)
            if len(head) < 16:
                head += chunk[: 16 - len(head)]
            digest.update(chunk)
            spool.write(chunk)
        if size == 0:
            raise _reject("file_empty", "The file is empty", name)
        sniffed = sniff_mime(head)
        if sniffed is None:
            raise _reject(
                "file_type_not_allowed",
                "Only PDF, PNG and JPEG files are accepted",
                name,
                allowed=list(ALLOWED_MIME_TYPES),
            )
        mime, ext = sniffed
        check_name(name, mime)
        check_declared_type(declared_type, mime, name)
    except BaseException:
        spool.close()
        raise
    spool.seek(0)
    return ValidatedFile(
        filename=safe_filename(name, ext),
        original_filename=name,
        mime_type=mime,
        size=size,
        sha256=digest.hexdigest(),
        file=spool,
    )


def validate_upload(
    original: str | None, data: bytes, max_bytes: int, declared_type: str | None = None
) -> ValidatedFile:
    """In-memory variant (tests, scripts)."""
    import io

    return validate_stream(original, io.BytesIO(data), max_bytes, declared_type)
