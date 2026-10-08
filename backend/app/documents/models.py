import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPrimaryKey, str_enum


class DocumentKind(enum.StrEnum):
    ATTACHMENT = "ATTACHMENT"  # supporting document provided by the student
    ISSUED = "ISSUED"  # final document produced by the administration
    MESSAGE = "MESSAGE"  # file attached to a message


class ScanStatus(enum.StrEnum):
    # No antivirus is wired yet (Phase 3): files are explicitly marked as not scanned.
    NOT_SCANNED = "NOT_SCANNED"
    PENDING = "PENDING"
    CLEAN = "CLEAN"
    INFECTED = "INFECTED"


class Document(UUIDPrimaryKey, Base):
    """File metadata. The content lives in object storage under `storage_key`, never in the database."""

    __tablename__ = "documents"

    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requests.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Supporting document for a specific requested document type.
    request_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("request_items.id", ondelete="RESTRICT")
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("request_messages.id", ondelete="RESTRICT"), index=True
    )
    kind: Mapped[DocumentKind] = mapped_column(str_enum(DocumentKind, "document_kind"), nullable=False)
    filename: Mapped[str] = mapped_column(String(128), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    scan_status: Mapped[ScanStatus] = mapped_column(
        str_enum(ScanStatus, "scan_status"), nullable=False, default=ScanStatus.NOT_SCANNED
    )
    uploaded_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
