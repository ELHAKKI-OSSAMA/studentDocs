"""Re-queues antivirus scans.

Usage:
    python -m app.scripts.rescan            # documents still SCANNING (lost messages, long outage)
    python -m app.scripts.rescan --errors   # also documents in ERROR (after fixing ClamAV)
"""

import argparse
import asyncio
import logging
import sys

from sqlalchemy import update
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.documents.models import Document, ScanStatus
from app.worker.tasks import enqueue_pending_scans

logger = logging.getLogger(__name__)


async def _reset_errors(database_url: str) -> int:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(
                update(Document)
                .where(Document.scan_status == ScanStatus.ERROR, Document.deleted_at.is_(None))
                .values(scan_status=ScanStatus.SCANNING, scan_detail=None)
            )
            return result.rowcount
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--errors", action="store_true", help="also rescan documents in ERROR")
    args = parser.parse_args()
    settings = get_settings()
    configure_logging(settings.log_level)
    if args.errors:
        logger.info(
            "%d documents in ERROR reset to SCANNING", asyncio.run(_reset_errors(settings.database_url))
        )
    logger.info("%d scans queued", enqueue_pending_scans())
    return 0


if __name__ == "__main__":
    sys.exit(main())
