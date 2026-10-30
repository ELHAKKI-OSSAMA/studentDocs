"""Inbound email: mailboxes, raw messages (immutable), processing cases and human review decisions.

email_accounts ──< email_messages ──1:1── email_cases ──< email_case_reviews
                                               │    └──< ai_extractions (app.ai.models)
                                               └──< documents (EMAIL_ATTACHMENT)
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, Timestamps, UUIDPrimaryKey, str_enum
from app.students.models import Student
from app.users.models import User


class EmailProviderKind(enum.StrEnum):
    IMAP = "IMAP"
    # Reserved for later phases (no implementation yet).
    MS_GRAPH = "MS_GRAPH"
    GMAIL = "GMAIL"


class EmailCaseStatus(enum.StrEnum):
    NEW = "NEW"  # stored, not processed yet
    AI_PROCESSING = "AI_PROCESSING"  # attachments being scanned and/or extraction running
    NEEDS_REVIEW = "NEEDS_REVIEW"  # waiting for a human (always, whatever the review confidence)
    CONVERTED = "CONVERTED"  # a NEW request was created from it (human decision)
    LINKED = "LINKED"  # attached to an EXISTING request (human decision)
    DISMISSED = "DISMISSED"  # read by a human, no follow-up (reason required)
    FAILED = "FAILED"  # technical failure (unparseable, storage, too large); can be retried
    IGNORED = "IGNORED"  # set aside before any AI by a deterministic rule (auto-reply, bounce, loop, …)


# Decided by a human: nothing changes them afterwards except an explicit, audited reopening.
CLOSED_CASE_STATUSES = frozenset(
    {EmailCaseStatus.CONVERTED, EmailCaseStatus.LINKED, EmailCaseStatus.DISMISSED, EmailCaseStatus.IGNORED}
)


class IdentificationMethod(enum.StrEnum):
    INSTITUTIONAL_EMAIL = "INSTITUTIONAL_EMAIL"  # known institutional address + favorable authentication
    KNOWN_EMAIL = "KNOWN_EMAIL"  # known (non-institutional) address + favorable authentication
    ADMIN_MANUAL = "ADMIN_MANUAL"  # chosen by a staff member


class ReviewConfidence(enum.StrEnum):
    """Deterministic completeness / quality level computed by the code to sort the review queue.

    It is NOT a probability that the AI is right, and it never triggers any action."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ReviewDecision(enum.StrEnum):
    ASSOCIATE_STUDENT = "ASSOCIATE_STUDENT"
    CORRECT = "CORRECT"
    CONVERT = "CONVERT"
    LINK = "LINK"
    DISMISS = "DISMISS"
    IGNORE = "IGNORE"
    REOPEN = "REOPEN"
    RETRY = "RETRY"
    REEXTRACT = "REEXTRACT"
    ASSIGN = "ASSIGN"


class EmailAccount(UUIDPrimaryKey, Timestamps, Base):
    """A watched mailbox. Credentials stay in the environment (IMAP_*), never in the database."""

    __tablename__ = "email_accounts"

    provider: Mapped[EmailProviderKind] = mapped_column(
        str_enum(EmailProviderKind, "email_provider"), nullable=False, default=EmailProviderKind.IMAP
    )
    address: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    folder: Mapped[str] = mapped_column(String(255), nullable=False, default="INBOX")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # IMAP cursor: UIDs are only meaningful within one UIDVALIDITY.
    uid_validity: Mapped[int | None] = mapped_column(BigInteger)
    last_seen_uid: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Error code only (never a secret, never server output).
    last_error: Mapped[str | None] = mapped_column(String(255))


class EmailMessage(UUIDPrimaryKey, Base):
    """A received message, exactly as fetched. Append-only (UPDATE/DELETE forbidden by trigger).

    The raw .eml lives in private object storage (`raw_storage_key`, never sent to clients)."""

    __tablename__ = "email_messages"
    __table_args__ = (
        # IMAP-level idempotence.
        UniqueConstraint("account_id", "uid_validity", "provider_uid", name="uq_email_messages_uid"),
        # RFC-level idempotence (a Message-ID is processed once per mailbox).
        Index(
            "uq_email_messages_message_id",
            "account_id",
            "message_id_header",
            unique=True,
            postgresql_where=text("message_id_header IS NOT NULL"),
        ),
        Index("ix_email_messages_received_at", "received_at"),
        CheckConstraint("raw_size_bytes > 0", name="raw_size_positive"),
    )

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("email_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    uid_validity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    provider_uid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id_header: Mapped[str | None] = mapped_column(String(998))
    in_reply_to: Mapped[str | None] = mapped_column(Text)
    references_header: Mapped[str | None] = mapped_column(Text)
    from_address: Mapped[str] = mapped_column(CITEXT, nullable=False, index=True)
    from_name: Mapped[str | None] = mapped_column(String(255))
    to_addresses: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    cc_addresses: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    subject: Mapped[str] = mapped_column(String(998), nullable=False, default="")
    # Date header (set by the sender, not trusted) and server reception time (IMAP INTERNALDATE).
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_storage_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    raw_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    raw_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Summary of the trusted Authentication-Results headers (only what the receiving server wrote).
    auth_results: Mapped[dict | None] = mapped_column(JSONB)
    # Bounded provider data (IMAP flags, folder). Never the body.
    provider_metadata: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EmailCase(UUIDPrimaryKey, Timestamps, Base):
    """The processing file of one received message, up to a human decision."""

    __tablename__ = "email_cases"
    __table_args__ = (
        Index("ix_email_cases_status_created_at", "status", "created_at"),
        CheckConstraint(
            "status NOT IN ('CONVERTED', 'LINKED') OR linked_request_id IS NOT NULL", name="linked_request"
        ),
        CheckConstraint("status <> 'CONVERTED' OR student_id IS NOT NULL", name="converted_student"),
        CheckConstraint("status <> 'DISMISSED' OR dismiss_reason IS NOT NULL", name="dismiss_reason"),
    )

    email_message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("email_messages.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    status: Mapped[EmailCaseStatus] = mapped_column(
        str_enum(EmailCaseStatus, "email_case_status"), nullable=False, default=EmailCaseStatus.NEW
    )
    # Set automatically only on strong proof (known address + favorable authentication), else by a human.
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students.id", ondelete="RESTRICT"), index=True
    )
    identification_method: Mapped[IdentificationMethod | None] = mapped_column(
        str_enum(IdentificationMethod, "email_identification_method")
    )
    # [{student_id, reasons: [...], score}] — deterministic evidence, never decided by the AI.
    candidate_students: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    detected_reference: Mapped[str | None] = mapped_column(String(20))
    linked_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requests.id", ondelete="RESTRICT"), index=True
    )
    # Deterministic signals: auto_reply, duplicate_of, injection_suspected, ai_failed, infected_attachment, …
    flags: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Sanitized, bounded text (what staff and the AI see) and sanitized HTML (display only, sandboxed).
    body_text: Mapped[str | None] = mapped_column(Text)
    body_html_sanitized: Mapped[str | None] = mapped_column(Text)
    # Latest deterministic review confidence (queue sorting only; never an authorization).
    review_confidence: Mapped[ReviewConfidence | None] = mapped_column(
        str_enum(ReviewConfidence, "email_review_confidence"), index=True
    )
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismiss_reason: Mapped[str | None] = mapped_column(String(500))
    failure_code: Mapped[str | None] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    message: Mapped[EmailMessage] = relationship(lazy="joined")
    student: Mapped[Student | None] = relationship(lazy="joined")
    assigned_to: Mapped[User | None] = relationship(lazy="joined", foreign_keys=[assigned_to_id])

    __mapper_args__ = {"version_id_col": version}


class EmailCaseReview(UUIDPrimaryKey, Base):
    """Human decisions on a case. Append-only: what the AI proposed and what a human decided both stay."""

    __tablename__ = "email_case_reviews"

    email_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("email_cases.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    decision: Mapped[ReviewDecision] = mapped_column(
        str_enum(ReviewDecision, "email_review_decision"), nullable=False
    )
    corrected_output: Mapped[dict | None] = mapped_column(JSONB)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    actor: Mapped[User] = relationship(lazy="joined")


async def lock_case(db, case_id: uuid.UUID, *, skip_locked: bool = False) -> EmailCase | None:
    """Row lock on the case only (its eager joins include nullable sides, which cannot be locked)."""
    from sqlalchemy import select

    return await db.scalar(
        select(EmailCase)
        .where(EmailCase.id == case_id)
        .with_for_update(skip_locked=skip_locked, of=EmailCase)
        .execution_options(populate_existing=True)
    )
