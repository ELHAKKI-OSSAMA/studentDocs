import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.academic.schemas import CategoryRef, I18nText
from app.students.models import EnrollmentSource, EnrollmentStatus


class EnrollmentIn(BaseModel):
    academic_year_id: uuid.UUID
    branch_id: uuid.UUID
    study_level_id: uuid.UUID


class EnrollmentReview(BaseModel):
    """Admin review: verify / reject, optionally correcting the declared data."""

    status: EnrollmentStatus
    academic_year_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None
    study_level_id: uuid.UUID | None = None
    review_note: str | None = Field(default=None, max_length=1000)


class _YearRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    label: str
    status: str


class _BranchRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    name_i18n: I18nText
    category: CategoryRef


class _LevelRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    name_i18n: I18nText


class EnrollmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    academic_year: _YearRef
    branch: _BranchRef
    study_level: _LevelRef
    status: EnrollmentStatus
    source: EnrollmentSource
    review_note: str | None
    reviewed_at: datetime | None
    created_at: datetime


class StudentListItem(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    student_number: str | None
    is_active: bool
    email_verified: bool
    created_at: datetime


class StudentDetail(StudentListItem):
    enrollments: list[EnrollmentOut]


class EnrollmentReviewItem(EnrollmentOut):
    student_id: uuid.UUID
    student_name: str
    student_email: str
    student_number: str | None
    reviewer_name: str | None


# --- deposited originals --------------------------------------------------------------------------


class DepositIn(BaseModel):
    document_type_id: uuid.UUID
    deposited_on: date
    note: str | None = Field(default=None, max_length=1000)


class _DocumentTypeRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    name_i18n: I18nText


class DepositOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_type: _DocumentTypeRef
    deposited_on: date
    note: str | None
    returned_at: datetime | None
    created_at: datetime
