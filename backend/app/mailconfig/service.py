"""Effective outgoing mail relay: the super-admin configuration when enabled, otherwise the .env one."""

import base64
import hashlib
import logging
import smtplib
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record
from app.core.config import Settings
from app.core.crud import commit_or_conflict
from app.mailconfig.models import SmtpSecurity, SmtpSettings
from app.mailconfig.schemas import SmtpSettingsIn
from app.users.models import User

logger = logging.getLogger(__name__)
SINGLETON_ID = 1


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    ssl: bool
    starttls: bool
    username: str | None
    password: str | None
    mail_from: str
    source: str  # "database" | "environment"


def _fernet(settings: Settings) -> Fernet:
    digest = hashlib.sha256(b"studentdocs:smtp-password:" + settings.secret_key.get_secret_value().encode())
    return Fernet(base64.urlsafe_b64encode(digest.digest()))


def encrypt_password(settings: Settings, password: str) -> str:
    return _fernet(settings).encrypt(password.encode()).decode()


def decrypt_password(settings: Settings, token: str) -> str | None:
    """None when SECRET_KEY changed since the password was saved: it must be entered again."""
    try:
        return _fernet(settings).decrypt(token.encode()).decode()
    except InvalidToken:
        return None


def env_config(settings: Settings) -> SmtpConfig:
    return SmtpConfig(
        host=settings.smtp_host,
        port=settings.smtp_port,
        ssl=settings.smtp_ssl,
        starttls=settings.smtp_starttls and not settings.smtp_ssl,
        username=settings.smtp_username or None,
        password=settings.smtp_password.get_secret_value() if settings.smtp_password else None,
        mail_from=settings.mail_from,
        source="environment",
    )


def row_config(settings: Settings, row: SmtpSettings) -> SmtpConfig:
    password = decrypt_password(settings, row.password_encrypted) if row.password_encrypted else None
    return SmtpConfig(
        host=row.host,
        port=row.port,
        ssl=row.security == SmtpSecurity.SSL,
        starttls=row.security == SmtpSecurity.STARTTLS,
        username=row.username or None,
        password=password,
        mail_from=row.mail_from,
        source="database",
    )


def readable(settings: Settings, row: SmtpSettings) -> bool:
    return not row.password_encrypted or decrypt_password(settings, row.password_encrypted) is not None


async def effective_config(db: AsyncSession, settings: Settings) -> SmtpConfig:
    if not settings.smtp_use_database_settings:
        return env_config(settings)
    row = await db.get(SmtpSettings, SINGLETON_ID)
    if row is None or not row.is_enabled:
        return env_config(settings)
    if not readable(settings, row):
        logger.error("Stored SMTP password cannot be decrypted (SECRET_KEY changed?); using the .env relay")
        return env_config(settings)
    return row_config(settings, row)


def send_test(config: SmtpConfig, to: str) -> str | None:
    """Sends one test email synchronously. Returns None on success, else an error code (never a secret)."""
    from app.core.mailer import OutgoingEmail, send_with

    mail = OutgoingEmail(
        to=to,
        subject="StudentDocs - test SMTP",
        text="Ceci est un email de test envoyé depuis la configuration SMTP de StudentDocs.",
    )
    try:
        send_with(config, mail)
    except smtplib.SMTPAuthenticationError:
        return "smtp_authentication_failed"
    except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused):
        return "smtp_address_refused"
    except TimeoutError:
        return "smtp_timeout"
    except (smtplib.SMTPException, OSError) as exc:
        logger.warning("SMTP test failed: %s", type(exc).__name__)
        return "smtp_connection_failed"
    return None


class SmtpSettingsService:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    async def get(self) -> SmtpSettings | None:
        return await self.db.get(SmtpSettings, SINGLETON_ID)

    def candidate(self, data: SmtpSettingsIn, row: SmtpSettings | None) -> SmtpSettings:
        """Unsaved configuration built from the form; an omitted password keeps the stored one."""
        candidate = SmtpSettings(
            id=SINGLETON_ID,
            is_enabled=data.is_enabled,
            host=data.host,
            port=data.port,
            security=data.security,
            username=data.username,
            mail_from=data.mail_from,
        )
        if data.password:
            candidate.password_encrypted = encrypt_password(self.settings, data.password)
        elif not data.clear_password and data.username and row is not None:
            candidate.password_encrypted = row.password_encrypted
        return candidate

    async def save(self, data: SmtpSettingsIn, actor: User, ip: str | None) -> SmtpSettings:
        row = await self.get()
        new = self.candidate(data, row)
        if row is None:
            row = new
            self.db.add(row)
        else:
            for name in (
                "is_enabled",
                "host",
                "port",
                "security",
                "username",
                "mail_from",
                "password_encrypted",
            ):
                setattr(row, name, getattr(new, name))
        row.updated_by_id = actor.id
        record(
            self.db,
            actor_id=actor.id,
            action="SMTP_SETTINGS_UPDATED",
            entity="smtp_settings",
            entity_id=SINGLETON_ID,
            ip=ip,
            # Never the password itself, only whether it changed.
            details={
                "is_enabled": data.is_enabled,
                "host": data.host,
                "port": data.port,
                "security": data.security.value,
                "password_changed": bool(data.password) or data.clear_password,
            },
        )
        await commit_or_conflict(self.db)
        return await self.db.get(SmtpSettings, SINGLETON_ID, populate_existing=True)
