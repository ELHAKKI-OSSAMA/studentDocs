import enum
import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, str_enum


class SmtpSecurity(enum.StrEnum):
    NONE = "NONE"
    SSL = "SSL"  # implicit TLS, usually port 465
    STARTTLS = "STARTTLS"  # usually port 587


class SmtpSettings(Timestamps, Base):
    """Outgoing mail relay set by a super-admin (single row). Disabled or absent: the .env relay is used.
    The password is stored encrypted (Fernet, key derived from SECRET_KEY) and never returned by the API."""

    __tablename__ = "smtp_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="singleton"),
        CheckConstraint("port BETWEEN 1 AND 65535", name="port_range"),
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    host: Mapped[str] = mapped_column(String(253), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    security: Mapped[SmtpSecurity] = mapped_column(str_enum(SmtpSecurity, "smtp_security"), nullable=False)
    username: Mapped[str | None] = mapped_column(String(255))
    password_encrypted: Mapped[str | None] = mapped_column(Text)
    mail_from: Mapped[str] = mapped_column(String(320), nullable=False)
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
