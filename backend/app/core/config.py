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
    # Object keys are namespaced by tenant (single tenant for now; keeps multi-tenancy possible).
    storage_tenant: str = Field(default="default", pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")

    # Antivirus (ClamAV daemon, INSTREAM over TCP). Files stay unavailable until scanned CLEAN.
    clamav_host: str = "localhost"
    clamav_port: int = 3310
    clamav_timeout_seconds: float = 60.0
    # clamd StreamMaxLength (bytes). The same value configures the ClamAV container (docker-compose.yml):
    # a file larger than this could never be scanned, so MAX_UPLOAD_BYTES must not exceed it.
    clamav_stream_max_bytes: int = 25 * 1024 * 1024
    # Celery queue dedicated to scans, retries while ClamAV is unreachable, then ERROR (fail closed).
    scan_queue: str = "documents"
    scan_max_retries: int = 5
    scan_retry_base_seconds: int = 10

    # Inbound email (IMAP, read-only). Polling is disabled while IMAP_HOST is empty.
    imap_host: str = ""
    imap_port: int = 993
    imap_ssl: bool = True
    imap_username: str = ""
    imap_password: SecretStr | None = None
    imap_folder: str = "INBOX"
    # Watched address (the email_accounts row); defaults to IMAP_USERNAME.
    imap_address: str = ""
    imap_timeout_seconds: float = 30.0
    email_poll_seconds: int = 60
    email_poll_batch: int = 50
    # A larger message (RFC822.SIZE) is not downloaded: its case is FAILED / too_large.
    email_max_bytes: int = 25 * 1024 * 1024
    email_max_attachments: int = 10
    email_body_max_chars: int = 100_000
    email_html_max_bytes: int = 2 * 1024 * 1024
    # authserv-id of the receiving server(s) whose Authentication-Results headers are trusted. Any
    # other Authentication-Results header may have been written by the sender and is ignored.
    email_trusted_authserv_ids: list[str] = []
    email_queue: str = "email"
    email_process_max_retries: int = 3
    # Cases stuck in AI_PROCESSING longer than this are re-queued by the periodic sweep.
    email_stale_minutes: int = 15

    # AI extraction. "none": no extraction, every case goes to human review as is.
    ai_provider: Literal["none", "openai_compatible"] = "none"
    ai_base_url: str = ""
    ai_model: str = ""
    ai_api_key: SecretStr | None = None
    # A non-private endpoint is refused unless this explicit decision is set. There is never a fallback.
    ai_allow_external: bool = False
    ai_timeout_seconds: float = 60.0
    ai_max_input_chars: int = 12_000
    ai_max_output_tokens: int = 1_000
    ai_max_retries: int = 3
    ai_queue: str = "ai"
    # "json_schema" (structured output) or "json_object" for servers without schema support.
    ai_json_mode: Literal["json_schema", "json_object"] = "json_schema"
    # Attachments are never sent to the model in this phase (only the sanitized email body).
    ai_read_attachments: bool = False

    # Outgoing mail
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = False
    # Implicit TLS (port 465). Exclusive with smtp_starttls (port 587).
    smtp_ssl: bool = False
    # False: the super-admin relay (smtp_settings) is ignored and the .env relay always used (test stacks).
    smtp_use_database_settings: bool = True
    mail_from: str = "StudentDocs <no-reply@studentdocs.local>"

    @model_validator(mode="after")
    def _upload_limit_fits_the_antivirus(self) -> "Settings":
        # Refuse to start rather than accept files that would all end in ERROR (never scannable).
        if self.max_upload_bytes > self.clamav_stream_max_bytes:
            raise ValueError(
                f"MAX_UPLOAD_BYTES ({self.max_upload_bytes}) must be <= CLAMAV_STREAM_MAX_BYTES "
                f"({self.clamav_stream_max_bytes}): larger files could not be scanned by ClamAV"
            )
        return self

    @model_validator(mode="after")
    def _inbound_email_and_ai_are_consistent(self) -> "Settings":
        if self.imap_host and not self.imap_ssl and self.is_production:
            raise ValueError("IMAP_SSL must be true in production (credentials would travel in clear)")
        if self.ai_read_attachments:
            raise ValueError(
                "AI_READ_ATTACHMENTS is not supported yet: only the email body is sent to the AI"
            )
        if self.ai_provider != "none" and not (self.ai_base_url and self.ai_model):
            raise ValueError("AI_BASE_URL and AI_MODEL are required when AI_PROVIDER is set")
        return self

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
