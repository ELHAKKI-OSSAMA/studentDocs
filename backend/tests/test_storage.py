import urllib.error
import urllib.request
import uuid

import pytest

from app.core.storage import create_s3_client
from app.scripts.init_storage import ensure_bucket


@pytest.fixture
def s3(settings):
    return create_s3_client(settings)


def test_ensure_bucket_is_idempotent(s3):
    bucket = f"test-{uuid.uuid4().hex[:12]}"
    try:
        assert ensure_bucket(s3, bucket) is True
        assert ensure_bucket(s3, bucket) is False
    finally:
        s3.delete_bucket(Bucket=bucket)


def test_objects_are_private_but_presigned_urls_work(s3, settings):
    key = f"tests/{uuid.uuid4()}.txt"
    s3.put_object(Bucket=settings.s3_bucket, Key=key, Body=b"confidential")
    try:
        public_url = f"{settings.s3_endpoint_url}/{settings.s3_bucket}/{key}"
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(public_url, timeout=5)  # noqa: S310
        assert exc.value.code == 403

        signed = s3.generate_presigned_url(
            "get_object", Params={"Bucket": settings.s3_bucket, "Key": key}, ExpiresIn=60
        )
        with urllib.request.urlopen(signed, timeout=5) as res:  # noqa: S310
            assert res.read() == b"confidential"
    finally:
        s3.delete_object(Bucket=settings.s3_bucket, Key=key)
