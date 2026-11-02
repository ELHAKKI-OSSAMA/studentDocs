import boto3
from botocore.client import BaseClient
from botocore.config import Config

from app.core.config import Settings


def create_s3_client(settings: Settings) -> BaseClient:
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        config=Config(
            signature_version="s3v4",
            connect_timeout=3,
            read_timeout=5,
            retries={"max_attempts": 2},
            s3={"addressing_style": "path" if settings.s3_force_path_style else "auto"},
            # Checksums only when the operation requires them: S3-compatible stores (SeaweedFS, Supabase)
            # do not all accept the CRC32 headers newer boto3 versions send by default.
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )
