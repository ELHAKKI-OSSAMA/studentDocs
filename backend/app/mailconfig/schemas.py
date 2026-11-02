from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.mailconfig.models import SmtpSecurity

HOST_PATTERN = r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$"


class SmtpSettingsIn(BaseModel):
    is_enabled: bool
    host: str = Field(min_length=1, max_length=253, pattern=HOST_PATTERN)
    port: int = Field(ge=1, le=65535)
    security: SmtpSecurity
    username: str | None = Field(default=None, max_length=255)
    # Omitted / empty: keep the stored password. clear_password removes it.
    password: str | None = Field(default=None, max_length=512)
    clear_password: bool = False
    mail_from: str = Field(min_length=3, max_length=320)

    @field_validator("host", "username", "mail_from", mode="before")
    @classmethod
    def _strip(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @field_validator("mail_from")
    @classmethod
    def _no_header_injection(cls, v: str) -> str:
        if "\r" in v or "\n" in v:
            raise ValueError("invalid sender")
        return v

    @model_validator(mode="after")
    def _password_needs_a_username(self) -> "SmtpSettingsIn":
        # A password without a username is never used (no SMTP login): the relay would refuse every email.
        if self.password and not self.username:
            raise ValueError("a username is required with a password")
        return self


class SmtpTestIn(SmtpSettingsIn):
    """Tests the configuration as typed in the form (not necessarily saved yet)."""

    to: EmailStr


class SmtpTestResult(BaseModel):
    ok: bool
    error: str | None = None
    used_stored_password: bool = False


class SmtpSettingsOut(BaseModel):
    configured: bool
    is_enabled: bool
    host: str | None
    port: int | None
    security: SmtpSecurity | None
    username: str | None
    has_password: bool
    # False when SECRET_KEY changed after saving: the password must be entered again.
    password_readable: bool
    mail_from: str | None
    updated_at: datetime | None
    updated_by_name: str | None
    # Relay used right now ("database" or "environment") and the .env fallback (never its password).
    active_source: str
    environment_host: str
    environment_port: int
    # False on a test stack: the saved configuration is kept but never used.
    database_settings_allowed: bool
