import asyncio
import logging
import uuid

from celery.signals import worker_ready

from app.core.config import get_settings
from app.core.mailer import OutgoingEmail, send_with
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
    # The relay is read at send time: a super-admin change applies to the next email without a restart.
    config = asyncio.run(worker_context().smtp_config())
    send_with(config, OutgoingEmail(**mail))


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
    if outcome in (ScanOutcome.CLEAN, ScanOutcome.INFECTED, ScanOutcome.ERROR):
        # An email attachment is scanned: its case may now be ready for the extraction step.
        case_id = asyncio.run(ctx.email_case_of(uuid.UUID(document_id)))
        if case_id is not None:
            enqueue_extract(case_id)
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


# --- inbound email ------------------------------------------------------------------------------------


class RedisLock:
    """SET NX EX lock, released only by its owner (a slow holder cannot release someone else's lock)."""

    def __init__(self, client, key: str, ttl: int) -> None:
        self.client, self.key, self.ttl = client, key, ttl
        self.token = uuid.uuid4().hex

    def acquire(self) -> bool:
        return bool(self.client.set(self.key, self.token, nx=True, ex=self.ttl))

    def release(self) -> None:
        self.client.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end return 0",
            1,
            self.key,
            self.token,
        )


def _enqueue_process(case_id) -> None:
    process_email_task.apply_async(args=[str(case_id)], queue=worker_context().settings.email_queue)


def enqueue_extract(case_id) -> None:
    extract_email_task.apply_async(args=[str(case_id)], queue=worker_context().settings.ai_queue)


@celery_app.task(name="email.poll", bind=True, acks_late=False, ignore_result=True, time_limit=300)
def poll_mailbox_task(self) -> str:
    """Celery Beat, every EMAIL_POLL_SECONDS. A failed poll is not retried: the next tick is the retry."""
    ctx = worker_context()
    settings = ctx.settings
    if not settings.imap_host:
        return "disabled"
    lock = RedisLock(
        ctx.redis,
        f"{settings.redis_key_prefix}email:poll:{ctx.mailbox_address}",
        int(settings.imap_timeout_seconds * 10),
    )
    if not lock.acquire():
        return "locked"  # another poll of the same mailbox is running
    try:
        result = asyncio.run(ctx.poll())
    finally:
        lock.release()
    for case_id in result.new_case_ids:
        _enqueue_process(case_id)
    logger.info(
        "Mailbox polled: %d stored, %d duplicate(s), %d too large, error=%s",
        result.fetched,
        result.duplicates,
        result.too_large,
        result.error,
    )
    return result.error or "ok"


@celery_app.task(
    name="email.process", bind=True, acks_late=True, reject_on_worker_lost=True, max_retries=None
)
def process_email_task(self, case_id: str) -> str:
    ctx = worker_context()
    settings = ctx.settings
    try:
        outcome = asyncio.run(ctx.process(uuid.UUID(case_id)))
    except Exception as exc:
        # Storage or database unavailable: the step was rolled back, the case is still NEW.
        if self.request.retries >= settings.email_process_max_retries:
            logger.exception("Processing of email case %s failed for good", case_id)
            asyncio.run(ctx.process_failed(uuid.UUID(case_id), "processing_error"))
            return "FAILED"
        countdown = min(settings.scan_retry_base_seconds * 2**self.request.retries, 600)
        queue = (self.request.delivery_info or {}).get("routing_key") or settings.email_queue
        raise self.retry(exc=exc, countdown=countdown, queue=queue) from exc
    if outcome.value == "READY":
        enqueue_extract(case_id)
    return outcome.value


@celery_app.task(
    name="email.extract",
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=None,
    time_limit=int(get_settings().ai_timeout_seconds * 2) + 60,
)
def extract_email_task(self, case_id: str) -> str:
    """Runs once the case attachments are scanned. One extraction at a time per case (Redis lock)."""
    ctx = worker_context()
    settings = ctx.settings
    lock = RedisLock(
        ctx.redis, f"{settings.redis_key_prefix}email:extract:{case_id}", int(settings.ai_timeout_seconds * 3)
    )
    if not lock.acquire():
        return "locked"
    try:
        final = self.request.retries >= settings.ai_max_retries
        outcome = asyncio.run(ctx.extract(uuid.UUID(case_id), final_attempt=final))
    finally:
        lock.release()
    if outcome.value == "RETRY":
        countdown = min(settings.scan_retry_base_seconds * 2**self.request.retries, 600)
        queue = (self.request.delivery_info or {}).get("routing_key") or settings.ai_queue
        raise self.retry(countdown=countdown, queue=queue)
    return outcome.value


@celery_app.task(name="email.sweep", ignore_result=True)
def sweep_email_cases_task() -> str:
    """Celery Beat safety net: re-queues NEW cases whose message was lost and stale AI_PROCESSING cases."""
    ctx = worker_context()
    new, stale = asyncio.run(ctx.sweep())
    for case_id in new:
        _enqueue_process(case_id)
    for case_id in stale:
        enqueue_extract(case_id)
    return f"{len(new)} new, {len(stale)} in processing"
