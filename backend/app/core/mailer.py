"""Outgoing email. With Celery, delivery runs in the worker (task `mail.send`) so API requests never block
on SMTP; in the serverless profile (TASK_MODE=inline) it is sent during the request."""

import asyncio
import logging
import smtplib
from dataclasses import asdict, dataclass
from email.message import EmailMessage
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.config import Settings
    from app.mailconfig.service import SmtpConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OutgoingEmail:
    to: str
    subject: str
    text: str

    def to_dict(self) -> dict:
        return asdict(self)


def send_with(config: "SmtpConfig", mail: OutgoingEmail) -> None:
    """Sends through the given relay (see app.mailconfig.service.effective_config)."""
    msg = EmailMessage()
    msg["From"] = config.mail_from
    msg["To"] = mail.to
    msg["Subject"] = mail.subject
    msg.set_content(mail.text)
    smtp_class = smtplib.SMTP_SSL if config.ssl else smtplib.SMTP
    with smtp_class(config.host, config.port, timeout=15) as smtp:
        if config.starttls:
            smtp.starttls()
        if config.username and config.password:
            smtp.login(config.username, config.password)
        smtp.send_message(msg)


def queue_email(mail: OutgoingEmail) -> None:
    from app.worker.tasks import send_email

    send_email.delay(mail.to_dict())


async def deliver_email(db: "AsyncSession", settings: "Settings", mail: OutgoingEmail) -> None:
    """Queues the email (Celery) or sends it now (inline). Never raises: a failed delivery is logged and the
    user can ask again (e.g. resend the verification email)."""
    if settings.task_mode == "celery":
        queue_email(mail)
        return
    from app.mailconfig.service import effective_config

    config = await effective_config(db, settings)
    try:
        await asyncio.to_thread(send_with, config, mail)
    except (smtplib.SMTPException, OSError):
        logger.exception("Email delivery failed (relay %s:%s)", config.host, config.port)
