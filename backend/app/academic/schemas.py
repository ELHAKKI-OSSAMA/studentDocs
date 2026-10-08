import re
import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.academic.models import AcademicYearStatus, DeliveryMode

CODE_PATTERN = r"^[A-Z0-9][A-Z0-9_]{0,47}$"


class I18nText(BaseModel):
    """Translatable label. French is required (default language); EN/AR fall back to FR."""

    fr: str = Field(min_length=1, max_length=200)
    en: str | None = Field(default=None, max_length=200)
    ar: str | None = Field(default=None, max_length=200)

    @field_validator("fr", "en", "ar")
    @classmethod
    def _clean(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = " ".join(v.split())
        if re.search(r"[<>]|[\x00-\x1f]", v):
            raise ValueError("contains forbidden characters")
        return v or None


def _code(v: str) -> str:
    return v.strip().upper()


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


# --- academic years ------------------------------------------------------------------------------


class AcademicYearBase(BaseModel):
    start_date: date
    end_date: date
    status: AcademicYearStatus = AcademicYearStatus.ACTIVE


class AcademicYearIn(AcademicYearBase):
    label: str = Field(pattern=r"^\d{4}-\d{4}$")

    @model_validator(mode="after")
    def _check(self) -> "AcademicYearIn":
        first, second = (int(x) for x in self.label.split("-"))
        if second != first + 1:
            raise ValueError("label must be two consecutive years, e.g. 2026-2027")
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        return self


class AcademicYearUpdate(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    status: AcademicYearStatus | None = None


class AcademicYearOut(_Out, AcademicYearBase):
    label: str


# --- categories ----------------------------------------------------------------------------------


class BranchCategoryIn(BaseModel):
    code: str = Field(pattern=CODE_PATTERN)
    name_i18n: I18nText
    sort_order: int = Field(default=0, ge=0, le=1000)
    is_active: bool = True

    _code = field_validator("code", mode="before")(_code)


class BranchCategoryUpdate(BaseModel):
    name_i18n: I18nText | None = None
    sort_order: int | None = Field(default=None, ge=0, le=1000)
    is_active: bool | None = None


class BranchCategoryOut(_Out):
    code: str
    name_i18n: I18nText
    sort_order: int
    is_active: bool


class CategoryRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name_i18n: I18nText


# --- branches ------------------------------------------------------------------------------------


class BranchIn(BaseModel):
    category_id: uuid.UUID
    code: str = Field(pattern=CODE_PATTERN)
    name_i18n: I18nText
    is_active: bool = True

    _code = field_validator("code", mode="before")(_code)


class BranchUpdate(BaseModel):
    """The category is fixed after creation: enrollments rely on branch/level category consistency."""

    name_i18n: I18nText | None = None
    is_active: bool | None = None


class BranchOut(_Out):
    code: str
    name_i18n: I18nText
    is_active: bool
    category: CategoryRef


# --- study levels --------------------------------------------------------------------------------


class StudyLevelIn(BaseModel):
    category_id: uuid.UUID
    code: str = Field(pattern=r"^[A-Z0-9][A-Z0-9_]{0,15}$")
    name_i18n: I18nText
    sort_order: int = Field(default=0, ge=0, le=100)
    is_active: bool = True

    _code = field_validator("code", mode="before")(_code)


class StudyLevelUpdate(BaseModel):
    name_i18n: I18nText | None = None
    sort_order: int | None = Field(default=None, ge=0, le=100)
    is_active: bool | None = None


class StudyLevelOut(_Out):
    code: str
    name_i18n: I18nText
    sort_order: int
    is_active: bool
    category: CategoryRef


# --- document types ------------------------------------------------------------------------------


class DocumentTypeIn(BaseModel):
    code: str = Field(pattern=CODE_PATTERN)
    name_i18n: I18nText
    description_i18n: I18nText | None = None
    delivery_mode: DeliveryMode = DeliveryMode.DIGITAL
    requires_attachment: bool = False
    max_quantity: int = Field(default=1, ge=1, le=10)
    processing_days: int = Field(default=3, ge=0, le=90)
    is_active: bool = True
    allowed_category_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)

    _code = field_validator("code", mode="before")(_code)


class DocumentTypeUpdate(BaseModel):
    name_i18n: I18nText | None = None
    description_i18n: I18nText | None = None
    delivery_mode: DeliveryMode | None = None
    requires_attachment: bool | None = None
    max_quantity: int | None = Field(default=None, ge=1, le=10)
    processing_days: int | None = Field(default=None, ge=0, le=90)
    is_active: bool | None = None
    allowed_category_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)


class DocumentTypeOut(_Out):
    code: str
    name_i18n: I18nText
    description_i18n: I18nText | None
    delivery_mode: DeliveryMode
    requires_attachment: bool
    max_quantity: int
    processing_days: int
    is_active: bool
    allowed_categories: list[CategoryRef]
