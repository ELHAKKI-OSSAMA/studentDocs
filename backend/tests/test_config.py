import pytest
from pydantic import ValidationError

from app.core.config import Settings

BASE = {
    "database_url": "postgresql+asyncpg://u:p@db/x",
    "s3_access_key": "k",
    "s3_secret_key": "s",
}


def test_short_secret_is_rejected():
    with pytest.raises(ValidationError):
        Settings(**BASE, secret_key="too-short")


def test_placeholder_secret_rejected_in_production():
    with pytest.raises(ValidationError, match="placeholder"):
        Settings(**BASE, app_env="production", secret_key="change-me-change-me-change-me-change-me")


def test_strong_secret_accepted_in_production():
    s = Settings(**BASE, app_env="production", secret_key="Zq8v1Lx0pR4tW9yB2nM6cK3hJ7gF5dA0eS1uI8oP")
    assert s.is_production
    assert "Zq8v" not in repr(s)  # secrets are masked


SECRET = "Zq8v1Lx0pR4tW9yB2nM6cK3hJ7gF5dA0eS1uI8oP"


def test_upload_limit_cannot_exceed_the_antivirus_stream_limit():
    """Files larger than clamd's StreamMaxLength could never be scanned: refuse to start."""
    with pytest.raises(ValidationError, match="MAX_UPLOAD_BYTES"):
        Settings(**BASE, secret_key=SECRET, max_upload_bytes=30_000_000, clamav_stream_max_bytes=26_214_400)


def test_default_limits_are_consistent():
    s = Settings(**BASE, secret_key=SECRET, max_upload_bytes=10_485_760, clamav_stream_max_bytes=26_214_400)
    assert s.max_upload_bytes <= s.clamav_stream_max_bytes
    equal = Settings(**BASE, secret_key=SECRET, max_upload_bytes=1000, clamav_stream_max_bytes=1000)
    assert equal.max_upload_bytes == 1000
