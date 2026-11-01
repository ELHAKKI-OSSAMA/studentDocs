"""Resources used by worker tasks, built from settings (overridable in tests to target the test database)."""

import uuid
from dataclasses import dataclass, field
from datetime import timedelta

from redis import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.ai.extraction import ExtractionRunner, ExtractOutcome
from app.ai.factory import build_llm_provider
from app.core.config import Settings, get_settings
from app.core.storage import create_s3_client
from app.documents.scanner import ClamdScanner
from app.documents.scanning import ScanOutcome, pending_scans, scan_document
from app.documents.storage import ObjectStorage
from app.emails.imap import ImapProvider
from app.emails.ingestion import IngestionService, PollResult
from app.emails.processing import EmailProcessor, ProcessOutcome, mark_failed
from app.emails.provider import EmailProvider
from app.mailconfig.service import SmtpConfig, effective_config
from app.models import load_all_models

# The worker does not import the API routers: register every mapper explicitly (foreign keys).
load_all_models()


def build_email_provider(s: Settings) -> EmailProvider | None:
    if not s.imap_host:
        return None
    return ImapProvider(
        host=s.imap_host,
        port=s.imap_port,
        username=s.imap_username,
        password=s.imap_password.get_secret_value() if s.imap_password else "",
        folder=s.imap_folder,
        use_ssl=s.imap_ssl,
        timeout=s.imap_timeout_seconds,
    )


@dataclass
class WorkerContext:
    settings: Settings
    storage: ObjectStorage = field(init=False)
    scanner: ClamdScanner = field(init=False)
    redis: Redis = field(init=False)

    def __post_init__(self) -> None:
        s = self.settings
        self.storage = ObjectStorage(create_s3_client(s), s.s3_bucket, s.storage_tenant)
        self.scanner = ClamdScanner(s.clamav_host, s.clamav_port, s.clamav_timeout_seconds)
        self.redis = Redis.from_url(s.redis_url)

    def _sessionmaker(self):
        # One engine per task run: each run has its own event loop (asyncio.run), no pooling across loops.
        engine = create_async_engine(self.settings.database_url, poolclass=NullPool)
        return engine, async_sessionmaker(engine, expire_on_commit=False)

    async def smtp_config(self) -> SmtpConfig:
        engine, sessionmaker = self._sessionmaker()
        try:
            async with sessionmaker() as db:
                return await effective_config(db, self.settings)
        finally:
            await engine.dispose()

    async def scan(self, document_id: uuid.UUID, *, final_attempt: bool) -> ScanOutcome:
        engine, maker = self._sessionmaker()
        try:
            return await scan_document(
                maker, self.storage, self.scanner, document_id, final_attempt=final_attempt
            )
        finally:
            await engine.dispose()

    async def email_case_of(self, document_id: uuid.UUID) -> uuid.UUID | None:
        from app.documents.models import Document

        engine, maker = self._sessionmaker()
        try:
            async with maker() as db:
                doc = await db.get(Document, document_id)
                return doc.email_case_id if doc is not None and doc.request_id is None else None
        finally:
            await engine.dispose()

    async def pending(self) -> list[uuid.UUID]:
        engine, maker = self._sessionmaker()
        try:
            return await pending_scans(maker)
        finally:
            await engine.dispose()

    # --- inbound email ------------------------------------------------------------------------------

    @property
    def mailbox_address(self) -> str:
        s = self.settings
        return (s.imap_address or s.imap_username).strip().lower()

    async def poll(self, provider: EmailProvider | None = None) -> PollResult:
        s = self.settings
        provider = provider or build_email_provider(s)
        engine, maker = self._sessionmaker()
        try:
            service = IngestionService(
                maker,
                self.storage,
                provider,
                max_bytes=s.email_max_bytes,
                batch=s.email_poll_batch,
                trusted_authserv_ids=s.email_trusted_authserv_ids,
            )
            return await service.poll(self.mailbox_address, s.imap_folder)
        finally:
            await engine.dispose()

    async def process(self, case_id: uuid.UUID) -> ProcessOutcome:
        from app.documents.scanning import celery_scan_queue
        from app.documents.service import DocumentPipeline

        engine, maker = self._sessionmaker()
        try:
            pipeline = DocumentPipeline(self.storage, celery_scan_queue(self.settings.scan_queue))
            return await EmailProcessor(maker, self.storage, pipeline, self.settings).process(case_id)
        finally:
            await engine.dispose()

    async def process_failed(self, case_id: uuid.UUID, code: str) -> None:
        engine, maker = self._sessionmaker()
        try:
            await mark_failed(maker, case_id, code)
        finally:
            await engine.dispose()

    async def extract(self, case_id: uuid.UUID, *, final_attempt: bool) -> ExtractOutcome:
        s = self.settings
        engine, maker = self._sessionmaker()
        try:
            runner = ExtractionRunner(
                maker,
                build_llm_provider(s),
                max_input_chars=s.ai_max_input_chars,
                max_output_tokens=s.ai_max_output_tokens,
                stale_after=timedelta(minutes=s.email_stale_minutes),
            )
            return await runner.run(case_id, final_attempt=final_attempt)
        finally:
            await engine.dispose()

    async def sweep(self) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
        from app.emails.cases import cases_to_resume

        engine, maker = self._sessionmaker()
        try:
            async with maker() as db:
                return await cases_to_resume(
                    db, stale_after=timedelta(minutes=self.settings.email_stale_minutes)
                )
        finally:
            await engine.dispose()


_context: WorkerContext | None = None


def configure(settings: Settings) -> WorkerContext:
    global _context
    _context = WorkerContext(settings)
    return _context


def worker_context() -> WorkerContext:
    return _context or configure(get_settings())
