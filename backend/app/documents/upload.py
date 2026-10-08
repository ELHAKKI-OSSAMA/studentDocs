"""Bounded multipart parsing shared by every upload endpoint."""

from dataclasses import dataclass, field

from starlette.datastructures import UploadFile
from starlette.requests import Request

from app.core.config import Settings
from app.core.errors import AppError
from app.documents.validation import ValidatedFile, validate_stream

MAX_TEXT_FIELD_BYTES = 64 * 1024


@dataclass
class ParsedForm:
    fields: dict[str, str] = field(default_factory=dict)
    # (form field name, validated file)
    files: list[tuple[str, ValidatedFile]] = field(default_factory=list)

    def close(self) -> None:
        for _, file in self.files:
            file.close()


async def parse_multipart(request: Request, settings: Settings) -> ParsedForm:
    """Parses and validates every file (streamed, hashed) before any of them is stored."""
    content_type = request.headers.get("content-type", "")
    if not content_type.startswith("multipart/form-data"):
        raise AppError.of(415, "unsupported_media_type", "Expected multipart/form-data")
    max_files = settings.max_files_per_upload
    form = await request.form(max_files=max_files, max_fields=50, max_part_size=MAX_TEXT_FIELD_BYTES)
    parsed = ParsedForm()
    try:
        for name, value in form.multi_items():
            if isinstance(value, UploadFile):
                parsed.files.append(
                    (
                        name,
                        validate_stream(
                            value.filename, value.file, settings.max_upload_bytes, value.content_type
                        ),
                    )
                )
            else:
                parsed.fields[name] = value
    except BaseException:
        parsed.close()
        raise
    finally:
        await form.close()
    return parsed
