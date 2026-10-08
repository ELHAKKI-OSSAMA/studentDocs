from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_SECRET_MARKERS = ("change-me", "changeme", "replace", "placeholder")


class Settings(BaseSettings):
    """Application settings, read from the environment (never hardcode secrets)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    app_name: str = "StudentDocs"
    log_level: str = "INFO"

    secret_key: SecretStr = Field(min_length=32)
    cors_origins: list[str] = ["http://localhost:3000"]

    database_url: str
    redis_url: str = "redis://localhost:6379/0"

    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_access_key: SecretStr
    s3_secret_key: SecretStr
    s3_bucket: str = "studentdocs"

    # Public URL of the web app, used in links sent by email.
    frontend_url: str = "http://localhost:3000"

    # Auth / sessions
    access_token_ttl_seconds: int = 15 * 60
    refresh_token_ttl_seconds: int = 14 * 24 * 3600
    email_verification_ttl_seconds: int = 24 * 3600
    cookie_secure: bool = False
    # Proxies allowed to set X-Forwarded-For (CIDR). Only their header is trusted for client IPs.
    trusted_proxies: list[str] = []

    # Brute-force protection
    redis_key_prefix: str = "sd:"
    rate_limit_login_per_ip: int = 20
    rate_limit_login_window_seconds: int = 60
    rate_limit_register_per_ip: int = 10
    rate_limit_register_window_seconds: int = 3600
    login_max_failed_attempts: int = 5
    login_lockout_seconds: int = 15 * 60

    # Uploads (supporting documents, issued documents, message attachments)
    max_upload_bytes: int = 10 * 1024 * 1024
    max_files_per_upload: int = 10
    rate_limit_request_create_per_hour: int = 30

    # Outgoing mail
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = False
    mail_from: str = "StudentDocs <no-reply@studentdocs.local>"

    @model_validator(mode="after")
    def _reject_weak_secrets_in_production(self) -> "Settings":
        if self.app_env == "production":
            key = self.secret_key.get_secret_value().lower()
            if any(marker in key for marker in INSECURE_SECRET_MARKERS):
                raise ValueError(
                    "SECRET_KEY looks like a placeholder; generate a random value for production"
                )
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
