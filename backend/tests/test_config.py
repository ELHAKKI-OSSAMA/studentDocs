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
