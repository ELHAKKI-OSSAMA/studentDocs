import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import CITEXT, INET, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, Timestamps, UUIDPrimaryKey, str_enum


class Role(enum.StrEnum):
    STUDENT = "STUDENT"
    ADMIN = "ADMIN"
    SUPER_ADMIN = "SUPER_ADMIN"


class Locale(enum.StrEnum):
    FR = "fr"
    EN = "en"
    AR = "ar"


class IdentityProvider(enum.StrEnum):
    LOCAL = "LOCAL"
    CAS = "CAS"
    MICROSOFT = "MICROSOFT"
    GOOGLE = "GOOGLE"


class User(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    # NULL for accounts that only authenticate through an external identity provider.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(str_enum(Role, "user_role"), nullable=False, index=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    locale: Mapped[Locale] = mapped_column(str_enum(Locale, "user_locale"), nullable=False, default=Locale.FR)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Access tokens issued before this instant are rejected (logout-all, deactivation, role change).
    sessions_revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    identities: Mapped[list["AuthIdentity"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def is_admin(self) -> bool:
        return self.role in (Role.ADMIN, Role.SUPER_ADMIN)


class AuthIdentity(UUIDPrimaryKey, Timestamps, Base):
    """Login methods of a user. LOCAL today; CAS / MICROSOFT / GOOGLE plug in later."""

    __tablename__ = "auth_identities"
    __table_args__ = (UniqueConstraint("provider", "subject", name="uq_auth_identities_provider_subject"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[IdentityProvider] = mapped_column(
        str_enum(IdentityProvider, "identity_provider"), nullable=False
    )
    # Provider-specific stable identifier (for LOCAL: the normalized email).
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="identities")


class RefreshToken(UUIDPrimaryKey, Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("ix_refresh_tokens_family_id", "family_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # All tokens of one login session share a family; reuse of a rotated token revokes the family.
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(255))


class EmailVerificationToken(UUIDPrimaryKey, Base):
    __tablename__ = "email_verification_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Permission(Base):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False)


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role: Mapped[Role] = mapped_column(str_enum(Role, "role_permission_role"), primary_key=True)
    permission_code: Mapped[str] = mapped_column(
        String(64), ForeignKey("permissions.code", ondelete="CASCADE"), primary_key=True
    )


class AllowedEmailDomain(UUIDPrimaryKey, Timestamps, Base):
    """Institutional domains allowed for student self-registration."""

    __tablename__ = "allowed_email_domains"

    domain: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
