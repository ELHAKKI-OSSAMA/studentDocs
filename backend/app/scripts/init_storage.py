"""Idempotently creates the private document bucket. Works with any S3-compatible provider.

Usage: python -m app.scripts.init_storage
"""

import logging
import sys

from botocore.client import BaseClient
from botocore.exceptions import ClientError

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.storage import create_s3_client

logger = logging.getLogger(__name__)


def ensure_bucket(s3: BaseClient, bucket: str) -> bool:
    """Returns True if the bucket was created, False if it already existed."""
    try:
        s3.head_bucket(Bucket=bucket)
        return False
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in ("404", "NoSuchBucket", "NotFound"):
            raise
    s3.create_bucket(Bucket=bucket)
    return True


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    created = ensure_bucket(create_s3_client(settings), settings.s3_bucket)
    logger.info("Bucket %s %s", settings.s3_bucket, "created" if created else "already exists")
    return 0


if __name__ == "__main__":
    sys.exit(main())
