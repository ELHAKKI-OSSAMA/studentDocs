"""Antivirus pipeline: one idempotent scan step per document, run by the worker.

    upload → validation → private storage → SCANNING ─(queue)→ scan ─┬→ CLEAN
                                                                      ├→ INFECTED (object quarantined)
                                                                      └→ ERROR (retry exhausted, file
                                                                                 missing, scanner error)
Guarantees:
- Idempotent: the row is locked (`FOR UPDATE SKIP LOCKED`) and only a SCANNING document is processed;
  a duplicate or late task finds a final status (or a lock held by another worker) and does nothing.
- Crash-safe: if the worker dies mid-scan the transaction is rolled back, the document stays SCANNING
  and the message is redelivered (acks_late) or picked up by the startup sweep.
- Fail closed: only an explicit clamd `OK` sets CLEAN. Any exception ends in SCANNING (retry) or ERROR.
"""

import asyncio
import enum
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.service import record
from app.documents.models import Document, ScanDetail, ScanStatus
from app.documents.scanner import Scanner, ScannerError, ScannerUnavailable
from app.documents.storage import ObjectStorage, StorageError, StorageObjectMissing
from app.notifications.service import NotificationService, NotificationType
from app.requests.models import Request

logger = logging.getLogger(__name__)


class ScanOutcome(enum.StrEnum):
    CLEAN = "CLEAN"
    INFECTED = "INFECTED"
    ERROR = "ERROR"
    RETRY = "RETRY"  # scanner unavailable, attempts left: document stays SCANNING
    SKIPPED = "SKIPPED"  # already scanned, deleted, unknown, or being scanned by another worker


async def scan_document(
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: ObjectStorage,
    scanner: Scanner,
    document_id: uuid.UUID,
    *,
    final_attempt: bool,
) -> ScanOutcome:
    async with sessionmaker() as db:
        doc = await db.scalar(
            select(Document).where(Document.id == document_id).with_for_update(skip_locked=True)
        )
        if doc is None or doc.scan_status != ScanStatus.SCANNING or doc.deleted_at is not None:
            return ScanOutcome.SKIPPED
        doc.scan_attempts += 1
        signature: str | None = None
        try:
            key = doc.storage_key
            result = await asyncio.to_thread(lambda: scanner.scan(storage.open_chunks(key)))
            status = ScanStatus.INFECTED if result.infected else ScanStatus.CLEAN
            signature = result.signature
            detail = f"{ScanDetail.VIRUS_DETECTED}:{signature}" if result.infected else None
        except StorageObjectMissing:
            status, detail = ScanStatus.ERROR, ScanDetail.FILE_MISSING.value
        except (ScannerUnavailable, StorageError):
            if not final_attempt:
                logger.warning("Scanner unavailable, scan of %s will be retried", document_id)
                await db.commit()  # keeps the attempt count
                return ScanOutcome.RETRY
            status, detail = ScanStatus.ERROR, ScanDetail.SCANNER_UNAVAILABLE.value
        except ScannerError as exc:
            logger.warning("Scanner refused %s: %s", document_id, exc)
            status, detail = ScanStatus.ERROR, ScanDetail.SCANNER_ERROR.value
        except Exception:
            logger.exception("Scan of %s failed", document_id)
            status, detail = ScanStatus.ERROR, ScanDetail.SCAN_FAILED.value

        if status == ScanStatus.INFECTED:
            await _quarantine(storage, doc)
        doc.scan_status = status
        doc.scan_detail = detail
        doc.scanned_at = datetime.now(UTC)
        record(
            db,
            actor_id=None,
            action="DOCUMENT_SCANNED",
            entity="document",
            entity_id=doc.id,
            details={
                **doc.owner_details(),
                "result": status.value,
                "detail": detail,
                "attempts": doc.scan_attempts,
                "sha256": doc.sha256,
            },
        )
        # Email attachments have no uploader to notify: staff see the status on the email case.
        if status != ScanStatus.CLEAN and doc.request_id is not None and doc.uploaded_by_id is not None:
            request = await db.get(Request, doc.request_id)
            if request is not None:
                kind = (
                    NotificationType.DOCUMENT_INFECTED
                    if status == ScanStatus.INFECTED
                    else NotificationType.DOCUMENT_SCAN_FAILED
                )
                NotificationService(db).notify(doc.uploaded_by_id, kind, request)
        await db.commit()
        logger.info("Document %s scanned: %s", document_id, status.value)
        return ScanOutcome(status.value)


async def _quarantine(storage: ObjectStorage, doc: Document) -> None:
    """Moves an infected object out of the regular key space. Downloads are refused either way."""
    target = storage.quarantine_key(doc.storage_key)
    try:
        await storage.move(doc.storage_key, target)
    except Exception:
        # Still INFECTED (never downloadable); the object simply stays at its original key.
        logger.exception("Could not move infected document %s to quarantine", doc.id)
        return
    doc.storage_key = target
    doc.quarantined_at = datetime.now(UTC)


async def pending_scans(sessionmaker: async_sessionmaker[AsyncSession]) -> list[uuid.UUID]:
    async with sessionmaker() as db:
        rows = await db.scalars(
            select(Document.id).where(
                Document.scan_status == ScanStatus.SCANNING, Document.deleted_at.is_(None)
            )
        )
        return list(rows.all())


# --- queue -----------------------------------------------------------------------------------------


class ScanQueue:
    """Hands documents to the worker. Called only after the upload transaction has committed."""

    def __init__(self, send: Callable[[str], None]) -> None:
        self._send = send

    def enqueue(self, document_ids: list[uuid.UUID]) -> None:
        for document_id in document_ids:
            try:
                self._send(str(document_id))
            except Exception:
                # The document stays SCANNING (never downloadable) and the worker's startup sweep or
                # `python -m app.scripts.rescan` will pick it up.
                logger.exception("Could not enqueue the scan of %s", document_id)


def celery_scan_queue(queue_name: str) -> ScanQueue:
    from app.worker.tasks import scan_document_task

    return ScanQueue(lambda doc_id: scan_document_task.apply_async(args=[doc_id], queue=queue_name))
