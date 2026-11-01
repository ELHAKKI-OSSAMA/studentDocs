"""Outgoing email. Delivery runs in the worker (task `mail.send`) so API requests never block on SMTP."""

import smtplib
from dataclasses import asdict, dataclass
from email.message import EmailMessage
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.mailconfig.service import SmtpConfig


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
