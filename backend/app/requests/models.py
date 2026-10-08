import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.academic.models import AcademicYear, Branch, DocumentType, StudyLevel
from app.core.db import Base, Timestamps, UUIDPrimaryKey, str_enum
from app.students.models import Student, StudentEnrollment
from app.users.models import User


class RequestStatus(enum.StrEnum):
    SUBMITTED = "SUBMITTED"
    RECEIVED = "RECEIVED"
    IN_REVIEW = "IN_REVIEW"
    NEEDS_INFORMATION = "NEEDS_INFORMATION"
    PROCESSING = "PROCESSING"
    APPROVED = "APPROVED"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    DOCUMENT_AVAILABLE = "DOCUMENT_AVAILABLE"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


TERMINAL_STATUSES = frozenset({RequestStatus.COMPLETED, RequestStatus.REJECTED, RequestStatus.CANCELLED})


class RequestSource(enum.StrEnum):
    WEB = "WEB"
    EMAIL = "EMAIL"
    ADMIN_CREATED = "ADMIN_CREATED"


class RequestPriority(enum.StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"


class Request(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "requests"
    __table_args__ = (Index("ix_requests_status_created_at", "status", "created_at"),)

    reference: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # The verified enrollment the request relies on, plus a snapshot of its academic data.
    enrollment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("student_enrollments.id", ondelete="RESTRICT"), nullable=False
    )
    academic_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    study_level_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("study_levels.id", ondelete="RESTRICT"), nullable=False
    )
    source: Mapped[RequestSource] = mapped_column(
        str_enum(RequestSource, "request_source"), nullable=False, default=RequestSource.WEB
    )
    status: Mapped[RequestStatus] = mapped_column(str_enum(RequestStatus, "request_status"), nullable=False)
    priority: Mapped[RequestPriority] = mapped_column(
        str_enum(RequestPriority, "request_priority"), nullable=False, default=RequestPriority.NORMAL
    )
    # Manual assignment (MVP). Automatic assignment rules can later set the same field.
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    reason: Mapped[str | None] = mapped_column(Text)
    extra_info: Mapped[str | None] = mapped_column(Text)
    # Reason of the last rejection / cancellation.
    status_reason: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    student: Mapped[Student] = relationship(lazy="joined")
    enrollment: Mapped[StudentEnrollment] = relationship(lazy="joined")
    academic_year: Mapped[AcademicYear] = relationship(lazy="joined")
    branch: Mapped[Branch] = relationship(lazy="joined")
    study_level: Mapped[StudyLevel] = relationship(lazy="joined")
    assigned_to: Mapped[User | None] = relationship(lazy="joined", foreign_keys=[assigned_to_id])
    items: Mapped[list["RequestItem"]] = relationship(
        lazy="selectin",
        back_populates="request",
        cascade="all, delete-orphan",
        order_by="RequestItem.position",
    )

    __mapper_args__ = {"version_id_col": version}


class RequestItem(UUIDPrimaryKey, Base):
    __tablename__ = "request_items"
    __table_args__ = (
        UniqueConstraint("request_id", "document_type_id", name="uq_request_items_request_document_type"),
        CheckConstraint("quantity BETWEEN 1 AND 10", name="quantity_range"),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_types.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    request: Mapped[Request] = relationship(back_populates="items")
    document_type: Mapped[DocumentType] = relationship(lazy="joined")


class RequestStatusHistory(Base):
    """Append-only (UPDATE/DELETE forbidden by trigger): the timeline of a request."""

    __tablename__ = "request_status_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requests.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    from_status: Mapped[RequestStatus | None] = mapped_column(str_enum(RequestStatus, "history_from_status"))
    to_status: Mapped[RequestStatus] = mapped_column(
        str_enum(RequestStatus, "history_to_status"), nullable=False
    )
    # NULL = system transition.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    actor_role: Mapped[str] = mapped_column(String(16), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RequestSequence(Base):
    """Per-year counter used to build REQ-YYYY-NNNNNN atomically."""

    __tablename__ = "request_sequences"

    year: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    last_value: Mapped[int] = mapped_column(Integer, nullable=False)
