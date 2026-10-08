import enum
import uuid
from datetime import date

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, Timestamps, UUIDPrimaryKey, str_enum


class AcademicYearStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class DeliveryMode(enum.StrEnum):
    DIGITAL = "DIGITAL"  # PDF uploaded by the administration
    PICKUP = "PICKUP"  # physical document collected at the office


class AcademicYear(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "academic_years"
    __table_args__ = (
        CheckConstraint("end_date > start_date", name="dates_ordered"),
        CheckConstraint("label ~ '^[0-9]{4}-[0-9]{4}$'", name="label_format"),
    )

    label: Mapped[str] = mapped_column(String(9), unique=True, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[AcademicYearStatus] = mapped_column(
        str_enum(AcademicYearStatus, "academic_year_status"),
        nullable=False,
        default=AcademicYearStatus.ACTIVE,
    )


class BranchCategory(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "branch_categories"

    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name_i18n: Mapped[dict] = mapped_column(JSONB, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Branch(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "branches"
    __table_args__ = (UniqueConstraint("category_id", "code", name="uq_branches_category_code"),)

    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("branch_categories.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name_i18n: Mapped[dict] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    category: Mapped[BranchCategory] = relationship(lazy="joined")


class StudyLevel(UUIDPrimaryKey, Timestamps, Base):
    """Year of study within a category (L1, L2, M1…)."""

    __tablename__ = "study_levels"
    __table_args__ = (UniqueConstraint("category_id", "code", name="uq_study_levels_category_code"),)

    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("branch_categories.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    name_i18n: Mapped[dict] = mapped_column(JSONB, nullable=False)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    category: Mapped[BranchCategory] = relationship(lazy="joined")


document_type_categories = Table(
    "document_type_categories",
    Base.metadata,
    Column(
        "document_type_id",
        UUID(as_uuid=True),
        ForeignKey("document_types.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "category_id",
        UUID(as_uuid=True),
        ForeignKey("branch_categories.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class DocumentType(UUIDPrimaryKey, Timestamps, Base):
    """Catalog entry + its processing rules. No allowed categories means: available to all."""

    __tablename__ = "document_types"
    __table_args__ = (
        CheckConstraint("max_quantity BETWEEN 1 AND 10", name="max_quantity_range"),
        CheckConstraint("processing_days BETWEEN 0 AND 90", name="processing_days_range"),
    )

    code: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    name_i18n: Mapped[dict] = mapped_column(JSONB, nullable=False)
    description_i18n: Mapped[dict | None] = mapped_column(JSONB)
    delivery_mode: Mapped[DeliveryMode] = mapped_column(
        str_enum(DeliveryMode, "delivery_mode"), nullable=False, default=DeliveryMode.DIGITAL
    )
    requires_attachment: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    max_quantity: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    processing_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=3)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    allowed_categories: Mapped[list[BranchCategory]] = relationship(
        secondary=document_type_categories, lazy="selectin", order_by=BranchCategory.sort_order
    )
