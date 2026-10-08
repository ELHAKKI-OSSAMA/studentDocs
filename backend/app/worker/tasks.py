import asyncio
import logging
import uuid

from celery.signals import worker_ready

from app.core.config import get_settings
from app.core.mailer import OutgoingEmail, send_smtp
from app.documents.scanning import ScanOutcome
from app.worker.celery_app import celery_app
from app.worker.context import worker_context

logger = logging.getLogger(__name__)


@celery_app.task(name="system.ping")
def ping() -> str:
    """Round-trip check used by the worker health verification."""
    return "pong"


@celery_app.task(
    name="mail.send",
    autoretry_for=(OSError,),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=8,
)
def send_email(mail: dict) -> None:
    send_smtp(get_settings(), OutgoingEmail(**mail))


@celery_app.task(
    name="documents.scan",
    bind=True,
    acks_late=True,  # a crash mid-scan redelivers the message; the document is still SCANNING
    reject_on_worker_lost=True,
    max_retries=None,  # bounded by settings.scan_max_retries below
)
def scan_document_task(self, document_id: str) -> str:
    ctx = worker_context()
    settings = ctx.settings
    final = self.request.retries >= settings.scan_max_retries
    outcome = asyncio.run(ctx.scan(uuid.UUID(document_id), final_attempt=final))
    if outcome == ScanOutcome.RETRY:
        countdown = min(settings.scan_retry_base_seconds * 2**self.request.retries, 600)
        queue = (self.request.delivery_info or {}).get("routing_key") or settings.scan_queue
        raise self.retry(countdown=countdown, queue=queue)
    return outcome.value


def enqueue_pending_scans() -> int:
    """Re-queues every document still SCANNING (lost message, worker restart). Duplicates are harmless."""
    ctx = worker_context()
    ids = asyncio.run(ctx.pending())
    for document_id in ids:
        scan_document_task.apply_async(args=[str(document_id)], queue=ctx.settings.scan_queue)
    return len(ids)


@worker_ready.connect
def _sweep_on_start(sender=None, **_) -> None:
    try:
        count = enqueue_pending_scans()
        if count:
            logger.info("Re-queued %d pending document scans", count)
    except Exception:
        logger.exception("Startup scan sweep failed (documents stay SCANNING until the next sweep)")
