import uuid
from urllib.parse import quote

from fastapi import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record
from app.core.errors import NotFoundError
from app.documents.models import Document, DocumentKind, ScanStatus
from app.documents.storage import ObjectStorage
from app.documents.validation import ValidatedFile


class PendingUploads:
    """Files written to storage during a transaction; removed again if the transaction fails."""

    def __init__(self, storage: ObjectStorage) -> None:
        self.storage = storage
        self.keys: list[str] = []

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
        key = ObjectStorage.new_key(f"requests/{request_id}")
        await self.storage.put(key, file.data, file.mime_type)
        self.keys.append(key)
        doc = Document(
            request_id=request_id,
            request_item_id=request_item_id,
            message_id=message_id,
            kind=kind,
            filename=file.filename,
            mime_type=file.mime_type,
            size_bytes=file.size,
            sha256=file.sha256,
            storage_key=key,
            scan_status=ScanStatus.NOT_SCANNED,
            uploaded_by_id=uploaded_by,
        )
        db.add(doc)
        return doc

    async def rollback(self) -> None:
        await self.storage.delete_quietly(self.keys)
        self.keys.clear()


async def documents_of(db: AsyncSession, request_id: uuid.UUID) -> list[Document]:
    rows = await db.scalars(
        select(Document).where(Document.request_id == request_id).order_by(Document.created_at)
    )
    return list(rows.all())


async def download_response(
    db: AsyncSession,
    storage: ObjectStorage,
    doc: Document | None,
    *,
    actor_id: uuid.UUID,
    ip: str | None,
) -> Response:
    """Streams a file after the caller has been authorized, and audits the access."""
    if doc is None:
        raise NotFoundError("Document not found")
    data = await storage.get(doc.storage_key)
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
    ascii_name = doc.filename.encode("ascii", "replace").decode().replace('"', "_")
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(doc.filename)}"
    return Response(
        content=data,
        media_type=doc.mime_type,
        headers={
            "Content-Disposition": disposition,
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
