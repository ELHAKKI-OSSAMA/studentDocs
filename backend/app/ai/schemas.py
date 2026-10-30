"""The only shape an AI answer can take. Strict: unknown keys are refused, every string is bounded,
enumerations are closed, and every identity value must come with the exact quote it was read from
(checked against the email text by the code, see extraction.py)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MissingInfo = Literal[
    "student_identity", "academic_year", "branch", "level", "document_type", "quantity", "supporting_document"
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Evidence(_Strict):
    value: str = Field(min_length=1, max_length=200)
    # Exact excerpt of the email text containing the value (verified by the code).
    quote: str = Field(min_length=1, max_length=300)


class ExtractedItem(_Strict):
    # Must be one of the catalogue codes given in the prompt (closed list, verified by the code).
    document_type_code: str = Field(min_length=1, max_length=64)
    quantity: int | None = Field(default=None, ge=1, le=10)
    quote: str = Field(min_length=1, max_length=300)


class EmailExtraction(_Strict):
    is_document_request: bool | None = None
    student_number: Evidence | None = None
    student_email: Evidence | None = None
    full_name: Evidence | None = None
    academic_year_label: Evidence | None = None
    branch_hint: Evidence | None = None
    level_hint: Evidence | None = None
    requested_documents: list[ExtractedItem] = Field(default_factory=list, max_length=10)
    request_reference: str | None = Field(default=None, pattern=r"^REQ-\d{4}-\d{6}$")
    reason: str | None = Field(default=None, max_length=500)
    language: Literal["fr", "en", "ar", "other"] | None = None
    missing_information: list[MissingInfo] = Field(default_factory=list, max_length=7)
    # The model reports instructions found in the email (a signal for the reviewer, nothing more).
    suspicious_content: bool = False
    # Recorded for analysis only: never used in the review confidence, never an authorization.
    self_reported_confidence: float | None = Field(default=None, ge=0, le=1)


def json_schema() -> dict:
    return EmailExtraction.model_json_schema()
