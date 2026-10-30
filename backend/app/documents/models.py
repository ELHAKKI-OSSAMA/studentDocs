import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPrimaryKey, str_enum


class DocumentKind(enum.StrEnum):
    ATTACHMENT = "ATTACHMENT"  # supporting document provided by the student
    ISSUED = "ISSUED"  # final document produced by the administration
    MESSAGE = "MESSAGE"  # file attached to a message
    EMAIL_ATTACHMENT = "EMAIL_ATTACHMENT"  # file received by email (EmailCase), attached on conversion


class ScanStatus(enum.StrEnum):
    """Antivirus lifecycle. Only CLEAN files can ever be downloaded (fail closed)."""

    NOT_SCANNED = "NOT_SCANNED"  # stored without a scan (legacy rows); never downloadable
    SCANNING = "SCANNING"  # stored privately, scan queued or running
    CLEAN = "CLEAN"
    INFECTED = "INFECTED"  # moved to quarantine
    ERROR = "ERROR"  # scan could not complete (scanner down, file missing, …); can be rescanned


class ScanDetail(enum.StrEnum):
    """Machine-readable reason stored with INFECTED / ERROR (the signature name is kept for staff)."""

    VIRUS_DETECTED = "virus_detected"
    SCANNER_UNAVAILABLE = "scanner_unavailable"
    SCANNER_ERROR = "scanner_error"
    FILE_MISSING = "file_missing"
    SCAN_FAILED = "scan_failed"


class Document(UUIDPrimaryKey, Base):
    """File metadata. The content lives in private object storage under `storage_key`, never in the
    database, and `storage_key` is never sent to clients."""

    __tablename__ = "documents"
    __table_args__ = (
        # Identical content can be found across requests (duplicates are reported, never auto-deleted).
        Index("ix_documents_sha256", "sha256"),
        # Recovery sweep: files still waiting for a scan.
        Index("ix_documents_scanning", "scan_status", postgresql_where=text("scan_status = 'SCANNING'")),
        # Every file belongs to a request, to an email case, or to both (email attachment after conversion).
        CheckConstraint("num_nonnulls(request_id, email_case_id) >= 1", name="owner"),
        # Only email attachments have no human uploader (they come from the mailbox).
        CheckConstraint("uploaded_by_id IS NOT NULL OR kind = 'EMAIL_ATTACHMENT'", name="uploader"),
    )

    # NULL only for an email attachment that is not (yet) part of a request.
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requests.id", ondelete="RESTRICT"), index=True
    )
    # Email case the file was received with. Kept after conversion (same row, full traceability).
    email_case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("email_cases.id", ondelete="RESTRICT"), index=True
    )
    # Supporting document for a specific requested document type.
    request_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("request_items.id", ondelete="RESTRICT")
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("request_messages.id", ondelete="RESTRICT"), index=True
    )
    kind: Mapped[DocumentKind] = mapped_column(str_enum(DocumentKind, "document_kind"), nullable=False)
    # Normalized display name (safe for headers and file systems) and the name as uploaded (audit only).
    filename: Mapped[str] = mapped_column(String(128), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255))
    # Detected from the content (magic bytes), never taken from the client.
    mime_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    scan_status: Mapped[ScanStatus] = mapped_column(
        str_enum(ScanStatus, "scan_status"), nullable=False, default=ScanStatus.SCANNING
    )
    # ScanDetail code, or "virus_detected:<signature>" for infected files.
    scan_detail: Mapped[str | None] = mapped_column(String(255))
    scan_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quarantined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Soft delete (replaced issued document): metadata and audit trail are kept, the object is removed.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    # NULL for email attachments (received by the system, not uploaded by a user).
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def owner_details(self) -> dict:
        """Audit references of the request and/or email case the document belongs to."""
        details = {"request_id": str(self.request_id) if self.request_id else None}
        if self.email_case_id:
            details["email_case_id"] = str(self.email_case_id)
        return details

    @property
    def downloadable(self) -> bool:
        return self.scan_status == ScanStatus.CLEAN and self.deleted_at is None
