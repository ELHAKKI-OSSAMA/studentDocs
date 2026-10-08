import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.auth.schemas import PasswordPolicy, _clean_name
from app.users.models import Role


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    role: Role
    first_name: str
    last_name: str
    is_active: bool
    email_verified: bool
    last_login_at: datetime | None
    created_at: datetime


class AdminCreate(BaseModel):
    email: EmailStr
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    role: Literal[Role.ADMIN, Role.SUPER_ADMIN]
    password: str = Field(min_length=12, max_length=PasswordPolicy.MAX)

    _names = field_validator("first_name", "last_name")(_clean_name)
    _password = field_validator("password")(PasswordPolicy.check)


class UserUpdate(BaseModel):
    is_active: bool | None = None
    # Only staff roles can be exchanged; students never become staff through this endpoint.
    role: Literal[Role.ADMIN, Role.SUPER_ADMIN] | None = None


class EmailDomainIn(BaseModel):
    domain: str = Field(min_length=3, max_length=253, pattern=r"^([a-z0-9-]{1,63}\.)+[a-z]{2,63}$")

    @field_validator("domain", mode="before")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.strip().lower().lstrip("@") if isinstance(v, str) else v


class EmailDomainOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    domain: str
    is_active: bool
    created_at: datetime


class DashboardStats(BaseModel):
    students_total: int
    students_pending_verification: int
    staff_total: int
    active_academic_years: int
    active_branches: int
    active_document_types: int
    allowed_email_domains: int
    requests_today: int
    requests_open: int
    requests_unassigned: int
    requests_needing_information: int
    requests_assigned_to_me: int
    enrollments_pending: int
    requests_by_status: dict[str, int]
