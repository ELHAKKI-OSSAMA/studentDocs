import uuid
from datetime import UTC, datetime
from urllib.parse import quote

from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record
from app.core.errors import AppError, NotFoundError
from app.documents.models import Document, DocumentKind, ScanStatus
from app.documents.scanning import ScanQueue
from app.documents.storage import ObjectStorage, StorageObjectMissing
from app.documents.validation import ValidatedFile


class PendingUploads:
    """Files written to private storage during a transaction.

    - `rollback()` removes them again if the transaction fails;
    - `dispatch()` queues their antivirus scan once the transaction has committed (a scan must never
      run before the row exists, and a rolled-back upload must never be scanned).
    """

    def __init__(self, storage: ObjectStorage, queue: ScanQueue | None) -> None:
        self.storage = storage
        self.queue = queue
        self.keys: list[str] = []
        self.documents: list[Document] = []

    async def store(
        self,
        db: AsyncSession,
        file: ValidatedFile,
        *,
        request_id: uuid.UUID,
        kind: DocumentKind,
        uploaded_by: uuid.UUID,
        request_item_id: uuid.UUID | None = None,
        message_id: uuid.UUID | None = None,
    ) -> Document:
        key = self.storage.new_key(request_id)
        try:
            await self.storage.put_stream(key, file.file, file.mime_type)
        finally:
            file.close()
        self.keys.append(key)
        doc = Document(
            request_id=request_id,
            request_item_id=request_item_id,
            message_id=message_id,
            kind=kind,
            filename=file.filename,
            original_filename=file.original_filename,
            mime_type=file.mime_type,
            size_bytes=file.size,
            sha256=file.sha256,
            storage_key=key,
            # Never available before the antivirus says CLEAN.
            scan_status=ScanStatus.SCANNING,
            uploaded_by_id=uploaded_by,
        )
        db.add(doc)
        self.documents.append(doc)
        return doc

    async def rollback(self) -> None:
        await self.storage.delete_quietly(self.keys)
        self.keys.clear()
        self.documents.clear()

    def dispatch(self) -> None:
        if self.queue is not None:
            self.queue.enqueue([d.id for d in self.documents])


def audit_upload(db: AsyncSession, doc: Document, *, actor_id: uuid.UUID, ip: str | None) -> None:
    """Upload audit entry: metadata only, never the content."""
    record(
        db,
        actor_id=actor_id,
        action="DOCUMENT_UPLOADED",
        entity="document",
        entity_id=doc.id,
        ip=ip,
        details={
            "request_id": str(doc.request_id),
            "kind": doc.kind.value,
            "mime_type": doc.mime_type,
            "size_bytes": doc.size_bytes,
            "sha256": doc.sha256,
        },
    )


async def documents_of(db: AsyncSession, request_id: uuid.UUID) -> list[Document]:
    rows = await db.scalars(
        select(Document)
        .where(Document.request_id == request_id, Document.deleted_at.is_(None))
        .order_by(Document.created_at)
    )
    return list(rows.all())


async def find_document(db: AsyncSession, request_id: uuid.UUID, document_id: uuid.UUID) -> Document | None:
    """A document of this request (a document id from another request is simply not found)."""
    return await db.scalar(
        select(Document).where(
            Document.id == document_id, Document.request_id == request_id, Document.deleted_at.is_(None)
        )
    )


async def download_response(
    db: AsyncSession,
    storage: ObjectStorage,
    doc: Document | None,
    *,
    actor_id: uuid.UUID,
    ip: str | None,
) -> StreamingResponse:
    """Streams a file after the caller has been authorized for the request. Only CLEAN files are served."""
    if doc is None:
        raise NotFoundError("Document not found")
    if not doc.downloadable:
        record(
            db,
            actor_id=actor_id,
            action="DOCUMENT_DOWNLOAD_REFUSED",
            entity="document",
            entity_id=doc.id,
            ip=ip,
            details={"request_id": str(doc.request_id), "scan_status": doc.scan_status.value},
        )
        await db.commit()
        raise AppError.of(
            409,
            "document_not_available",
            "This file is not available (antivirus scan pending or failed)",
            {"scan_status": doc.scan_status.value},
        )
    try:
        chunks = await storage.open(doc.storage_key)
    except StorageObjectMissing as exc:
        raise NotFoundError("Document not found") from exc
    record(
        db,
        actor_id=actor_id,
        action="DOCUMENT_DOWNLOADED",
        entity="document",
        entity_id=doc.id,
        ip=ip,
        details={"request_id": str(doc.request_id), "kind": doc.kind.value},
    )
    await db.commit()
    ascii_name = doc.filename.encode("ascii", "replace").decode().replace('"', "_").replace("?", "_")
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(doc.filename)}"
    return StreamingResponse(
        chunks,  # blocking iterator: Starlette consumes it in a thread pool
        media_type=doc.mime_type,
        headers={
            "Content-Disposition": disposition,
            "Content-Length": str(doc.size_bytes),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


def soft_delete(db: AsyncSession, doc: Document, *, actor_id: uuid.UUID, ip: str | None) -> str:
    """Marks the document deleted (metadata stays for the audit trail) and returns the object key, which
    the caller removes from storage once the transaction has committed."""
    doc.deleted_at = datetime.now(UTC)
    doc.deleted_by_id = actor_id
    record(
        db,
        actor_id=actor_id,
        action="DOCUMENT_DELETED",
        entity="document",
        entity_id=doc.id,
        ip=ip,
        details={"request_id": str(doc.request_id), "kind": doc.kind.value, "sha256": doc.sha256},
    )
    return doc.storage_key


class DocumentPipeline:
    """Private storage + antivirus queue, shared by every upload path (student, admin, messages)."""

    def __init__(self, storage: ObjectStorage, queue: ScanQueue | None) -> None:
        self.storage = storage
        self.queue = queue

    def uploads(self) -> PendingUploads:
        return PendingUploads(self.storage, self.queue)
