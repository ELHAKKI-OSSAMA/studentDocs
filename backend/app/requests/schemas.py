import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.academic.models import DeliveryMode
from app.academic.schemas import CategoryRef, I18nText
from app.documents.models import DocumentKind, ScanStatus
from app.messages.models import AuthorSide, MessageKind
from app.requests.models import RequestPriority, RequestSource, RequestStatus
from app.students.models import EnrollmentStatus


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.replace("\x00", "").strip()
    return value or None


class RequestItemIn(BaseModel):
    document_type_id: uuid.UUID
    quantity: int = Field(default=1, ge=1, le=10)


class RequestCreate(BaseModel):
    enrollment_id: uuid.UUID
    items: list[RequestItemIn] = Field(min_length=1, max_length=10)
    reason: str | None = Field(default=None, max_length=1000)
    extra_info: str | None = Field(default=None, max_length=2000)

    _texts = field_validator("reason", "extra_info")(_clean_text)

    @model_validator(mode="after")
    def _unique_types(self) -> "RequestCreate":
        ids = [i.document_type_id for i in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("each document type can only be requested once")
        return self


class TransitionIn(BaseModel):
    to_status: RequestStatus
    comment: str | None = Field(default=None, max_length=2000)

    _comment = field_validator("comment")(_clean_text)


class AssignIn(BaseModel):
    assignee_id: uuid.UUID | None


# --- output ---------------------------------------------------------------------------------------


class _Ref(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class YearRef(_Ref):
    id: uuid.UUID
    label: str


class BranchRef(_Ref):
    id: uuid.UUID
    code: str
    name_i18n: I18nText
    category: CategoryRef


class LevelRef(_Ref):
    id: uuid.UUID
    code: str
    name_i18n: I18nText


class DocumentTypeRef(_Ref):
    id: uuid.UUID
    code: str
    name_i18n: I18nText
    delivery_mode: DeliveryMode
    requires_attachment: bool


class ItemOut(_Ref):
    id: uuid.UUID
    quantity: int
    document_type: DocumentTypeRef


class DocumentOut(_Ref):
    id: uuid.UUID
    kind: DocumentKind
    filename: str
    mime_type: str
    size_bytes: int
    scan_status: ScanStatus
    request_item_id: uuid.UUID | None
    message_id: uuid.UUID | None
    created_at: datetime


class HistoryOut(_Ref):
    from_status: RequestStatus | None
    to_status: RequestStatus
    actor_role: str
    comment: str | None
    created_at: datetime


class PersonRef(BaseModel):
    id: uuid.UUID
    first_name: str
    last_name: str


class StudentInfo(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    first_name: str
    last_name: str
    email: str
    student_number: str | None


class RequestListItem(BaseModel):
    id: uuid.UUID
    reference: str
    status: RequestStatus
    source: RequestSource
    priority: RequestPriority
    created_at: datetime
    updated_at: datetime
    academic_year: YearRef
    branch: BranchRef
    items: list[ItemOut]
    unread_messages: int
    student: StudentInfo | None = None  # staff views only
    assigned_to: PersonRef | None = None  # staff views only


class RequestDetail(RequestListItem):
    study_level: LevelRef
    enrollment_status: EnrollmentStatus
    reason: str | None
    extra_info: str | None
    status_reason: str | None
    submitted_at: datetime
    closed_at: datetime | None
    documents: list[DocumentOut]
    history: list[HistoryOut]
    # Computed server-side from the state machine and the caller's permissions: the UI never guesses.
    available_transitions: list[RequestStatus]
    can_cancel: bool
    can_respond: bool
    can_message: bool
    can_assign: bool
    can_upload_document: bool


class MessageOut(BaseModel):
    id: uuid.UUID
    author_side: AuthorSide
    author_name: str
    kind: MessageKind
    body: str
    created_at: datetime
    read_at: datetime | None
    attachments: list[DocumentOut]


class RequestSummary(BaseModel):
    pending: int
    in_progress: int
    action_required: int
    completed: int
    closed: int


class IssuedDocumentOut(DocumentOut):
    request_id: uuid.UUID
    reference: str
