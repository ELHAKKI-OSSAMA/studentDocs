import re
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.users.models import Locale, Role

_NAME = Field(min_length=1, max_length=100)


def _clean_name(value: str) -> str:
    value = " ".join(value.split())
    if not value:
        raise ValueError("must not be blank")
    if re.search(r"[<>\"`{}]|[\x00-\x1f]", value):
        raise ValueError("contains forbidden characters")
    return value


class PasswordPolicy:
    MIN = 10
    MAX = 128

    @staticmethod
    def check(value: str) -> str:
        if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
            raise ValueError("must contain at least one letter and one digit")
        return value


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=PasswordPolicy.MIN, max_length=PasswordPolicy.MAX)
    first_name: str = _NAME
    last_name: str = _NAME
    student_number: str | None = Field(default=None, pattern=r"^[A-Za-z0-9]{4,32}$")
    locale: Locale = Locale.FR

    _names = field_validator("first_name", "last_name")(_clean_name)
    _password = field_validator("password")(PasswordPolicy.check)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=PasswordPolicy.MAX)


class TokenIn(BaseModel):
    token: str = Field(min_length=16, max_length=200)


class EmailIn(BaseModel):
    email: EmailStr


class StudentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    student_number: str | None


class MeOut(BaseModel):
    id: uuid.UUID
    email: str
    role: Role
    first_name: str
    last_name: str
    locale: Locale
    permissions: list[str]
    student: StudentSummary | None = None


class MeUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    locale: Locale | None = None

    @field_validator("first_name", "last_name")
    @classmethod
    def _names(cls, v: str | None) -> str | None:
        return None if v is None else _clean_name(v)


class AcceptedOut(BaseModel):
    status: str = "accepted"
