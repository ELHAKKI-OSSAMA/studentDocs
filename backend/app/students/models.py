import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.academic.models import AcademicYear, Branch, StudyLevel
from app.core.db import Base, Timestamps, UUIDPrimaryKey, str_enum
from app.users.models import User


class EnrollmentStatus(enum.StrEnum):
    PENDING = "PENDING"  # declared, not yet checked by the administration
    VERIFIED = "VERIFIED"  # official: may back a document request
    REJECTED = "REJECTED"


class EnrollmentSource(enum.StrEnum):
    SELF_DECLARED = "SELF_DECLARED"
    ADMIN = "ADMIN"
    IMPORT = "IMPORT"  # reserved for a future CSV / Apogée import


class Student(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "students"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    # Institutional student number (CNE / Apogée), optional at self-registration.
    student_number: Mapped[str | None] = mapped_column(String(32), unique=True)

    user: Mapped[User] = relationship(lazy="joined")


class StudentEnrollment(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "student_enrollments"
    __table_args__ = (
        UniqueConstraint(
            "student_id", "academic_year_id", "branch_id", name="uq_student_enrollments_year_branch"
        ),
    )

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True
    )
    academic_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    study_level_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("study_levels.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[EnrollmentStatus] = mapped_column(
        str_enum(EnrollmentStatus, "enrollment_status"),
        nullable=False,
        default=EnrollmentStatus.PENDING,
        server_default=EnrollmentStatus.PENDING.value,
        index=True,
    )
    source: Mapped[EnrollmentSource] = mapped_column(
        str_enum(EnrollmentSource, "enrollment_source"),
        nullable=False,
        default=EnrollmentSource.SELF_DECLARED,
        server_default=EnrollmentSource.SELF_DECLARED.value,
    )
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text)

    student: Mapped[Student] = relationship(lazy="joined")
    academic_year: Mapped[AcademicYear] = relationship(lazy="joined")
    branch: Mapped[Branch] = relationship(lazy="joined")
    study_level: Mapped[StudyLevel] = relationship(lazy="joined")
    reviewed_by: Mapped[User | None] = relationship(lazy="joined", foreign_keys=[reviewed_by_id])
