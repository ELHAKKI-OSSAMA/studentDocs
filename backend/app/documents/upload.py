"""Bounded multipart parsing shared by every upload endpoint."""

from dataclasses import dataclass, field

from starlette.datastructures import UploadFile
from starlette.requests import Request

from app.core.config import Settings
from app.core.errors import AppError
from app.documents.validation import ValidatedFile, validate_upload

MAX_TEXT_FIELD_BYTES = 64 * 1024


@dataclass
class ParsedForm:
    fields: dict[str, str] = field(default_factory=dict)
    # (form field name, validated file)
    files: list[tuple[str, ValidatedFile]] = field(default_factory=list)


async def _read_limited(upload: UploadFile, max_bytes: int) -> bytes:
    data = await upload.read(max_bytes + 1)  # one extra byte detects oversize without reading it all
    return data


async def parse_multipart(request: Request, settings: Settings) -> ParsedForm:
    content_type = request.headers.get("content-type", "")
    if not content_type.startswith("multipart/form-data"):
        raise AppError.of(415, "unsupported_media_type", "Expected multipart/form-data")
    max_files = settings.max_files_per_upload
    form = await request.form(max_files=max_files, max_fields=50, max_part_size=MAX_TEXT_FIELD_BYTES)
    parsed = ParsedForm()
    try:
        for name, value in form.multi_items():
            if isinstance(value, UploadFile):
                data = await _read_limited(value, settings.max_upload_bytes)
                parsed.files.append((name, validate_upload(value.filename, data, settings.max_upload_bytes)))
            else:
                parsed.fields[name] = value
    finally:
        await form.close()
    return parsed
