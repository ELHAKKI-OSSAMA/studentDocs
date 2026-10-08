"""Resources used by worker tasks, built from settings (overridable in tests to target the test database)."""

import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings
from app.core.storage import create_s3_client
from app.documents.scanner import ClamdScanner
from app.documents.scanning import ScanOutcome, pending_scans, scan_document
from app.documents.storage import ObjectStorage
from app.models import load_all_models

# The worker does not import the API routers: register every mapper explicitly (foreign keys).
load_all_models()


@dataclass
class WorkerContext:
    settings: Settings
    storage: ObjectStorage = field(init=False)
    scanner: ClamdScanner = field(init=False)

    def __post_init__(self) -> None:
        s = self.settings
        self.storage = ObjectStorage(create_s3_client(s), s.s3_bucket, s.storage_tenant)
        self.scanner = ClamdScanner(s.clamav_host, s.clamav_port, s.clamav_timeout_seconds)

    def _sessionmaker(self):
        # One engine per task run: each run has its own event loop (asyncio.run), no pooling across loops.
        engine = create_async_engine(self.settings.database_url, poolclass=NullPool)
        return engine, async_sessionmaker(engine, expire_on_commit=False)

    async def scan(self, document_id: uuid.UUID, *, final_attempt: bool) -> ScanOutcome:
        engine, maker = self._sessionmaker()
        try:
            return await scan_document(
                maker, self.storage, self.scanner, document_id, final_attempt=final_attempt
            )
        finally:
            await engine.dispose()

    async def pending(self) -> list[uuid.UUID]:
        engine, maker = self._sessionmaker()
        try:
            return await pending_scans(maker)
        finally:
            await engine.dispose()


_context: WorkerContext | None = None


def configure(settings: Settings) -> WorkerContext:
    global _context
    _context = WorkerContext(settings)
    return _context


def worker_context() -> WorkerContext:
    return _context or configure(get_settings())
