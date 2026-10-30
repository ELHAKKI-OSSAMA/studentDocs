import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.emails.models import EmailCaseStatus, IdentificationMethod, ReviewConfidence, ReviewDecision
from app.requests.models import RequestStatus
from app.requests.schemas import DocumentOut, PersonRef


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.replace("\x00", "").strip()
    return value or None


class StudentRef(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    first_name: str
    last_name: str
    email: str
    student_number: str | None


class CandidateOut(BaseModel):
    student: StudentRef
    reasons: list[str]
    score: int
    evidence: dict = {}


class RequestRef(BaseModel):
    id: uuid.UUID
    reference: str
    status: RequestStatus
    student_id: uuid.UUID


class EmailCaseListItem(BaseModel):
    id: uuid.UUID
    status: EmailCaseStatus
    from_address: str
    from_name: str | None
    subject: str
    received_at: datetime
    review_confidence: ReviewConfidence | None
    student: StudentRef | None
    candidate_count: int
    detected_reference: str | None
    attachment_count: int
    assigned_to: PersonRef | None
    # Warning signals for the queue (never permissions).
    authentication: str
    injection_suspected: bool
    ai_failed: bool
    infected_attachment: bool
    created_at: datetime


class ExtractionOut(BaseModel):
    id: uuid.UUID
    provider: str
    model: str
    prompt_version: str
    is_local_provider: bool
    output: dict | None
    rule_violations: list
    error_code: str | None
    review_confidence: ReviewConfidence | None
    review_score: int | None
    latency_ms: int | None
    created_at: datetime


class ReviewOut(BaseModel):
    id: uuid.UUID
    decision: ReviewDecision
    actor: PersonRef
    corrected_output: dict | None
    comment: str | None
    created_at: datetime


class RejectedAttachment(BaseModel):
    filename: str
    code: str
    size_bytes: int


class EmailCaseDetail(EmailCaseListItem):
    to_addresses: list[str]
    cc_addresses: list[str]
    sent_at: datetime | None
    message_id_header: str | None
    identification_method: IdentificationMethod | None
    candidates: list[CandidateOut]
    body_text: str | None
    # Sanitized server side (nh3) and rendered by the client in a sandboxed iframe only.
    body_html: str | None
    flags: dict
    linked_request: RequestRef | None
    reference_request: RequestRef | None
    extraction: ExtractionOut | None
    correction: dict | None
    reviews: list[ReviewOut]
    documents: list[DocumentOut]
    rejected_attachments: list[RejectedAttachment]
    failure_code: str | None
    dismiss_reason: str | None
    version: int
    # What the current user may do on this case.
    can_process: bool
    can_convert: bool
    can_dismiss: bool
    can_read_raw: bool
    can_reextract: bool
    can_retry: bool
    can_reopen: bool


# --- inputs ------------------------------------------------------------------------------------------


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssignCaseIn(_In):
    assignee_id: uuid.UUID | None


class AssociateStudentIn(_In):
    student_id: uuid.UUID
    comment: str | None = Field(default=None, max_length=1000)

    _c = field_validator("comment")(_clean)


class CorrectedItem(_In):
    document_type_id: uuid.UUID
    quantity: int = Field(default=1, ge=1, le=10)


class CorrectionIn(_In):
    """The reviewer's version of the data. Stored next to (never over) the AI proposal."""

    student_number: str | None = Field(default=None, max_length=32)
    academic_year_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None
    study_level_id: uuid.UUID | None = None
    enrollment_id: uuid.UUID | None = None
    requested_documents: list[CorrectedItem] = Field(default_factory=list, max_length=10)
    reason: str | None = Field(default=None, max_length=1000)
    comment: str | None = Field(default=None, max_length=1000)

    _c = field_validator("student_number", "reason", "comment")(_clean)


class ConvertItemIn(_In):
    document_type_id: uuid.UUID
    quantity: int = Field(default=1, ge=1, le=10)
    # Email attachments (CLEAN only) given as supporting documents for this item.
    attachment_ids: list[uuid.UUID] = Field(default_factory=list, max_length=10)


class ConvertIn(_In):
    student_id: uuid.UUID
    enrollment_id: uuid.UUID
    items: list[ConvertItemIn] = Field(min_length=1, max_length=10)
    reason: str | None = Field(default=None, max_length=1000)
    extra_info: str | None = Field(default=None, max_length=2000)
    # Optimistic lock: the case version the reviewer saw.
    version: int

    _c = field_validator("reason", "extra_info")(_clean)

    @model_validator(mode="after")
    def _unique(self) -> "ConvertIn":
        ids = [i.document_type_id for i in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("each document type can only be requested once")
        attachments = [a for i in self.items for a in i.attachment_ids]
        if len(attachments) != len(set(attachments)):
            raise ValueError("an attachment can only support one requested document")
        return self


class LinkIn(_In):
    request_id: uuid.UUID
    attachment_ids: list[uuid.UUID] = Field(default_factory=list, max_length=10)
    # The email answers the information request of a NEEDS_INFORMATION request (→ IN_REVIEW).
    as_information_response: bool = False
    version: int


class ReasonIn(_In):
    reason: str = Field(min_length=1, max_length=500)

    _r = field_validator("reason")(_clean)


class CommentIn(_In):
    comment: str | None = Field(default=None, max_length=1000)

    _c = field_validator("comment")(_clean)


class EmailStats(BaseModel):
    by_status: dict[str, int]
    by_confidence: dict[str, int]
    awaiting_review: int
    oldest_awaiting_review_at: datetime | None
    received_last_24h: int
    ai_failed: int
    infected_attachments: int
    mailbox_last_polled_at: datetime | None
    mailbox_last_success_at: datetime | None
    mailbox_last_error: str | None
    ai_provider: str
    ai_is_local: bool | None
