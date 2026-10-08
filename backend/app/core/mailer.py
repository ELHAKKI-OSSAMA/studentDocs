"""Outgoing email. Delivery runs in the worker (task `mail.send`) so API requests never block on SMTP."""

import smtplib
from dataclasses import asdict, dataclass
from email.message import EmailMessage

from app.core.config import Settings


@dataclass(frozen=True)
class OutgoingEmail:
    to: str
    subject: str
    text: str

    def to_dict(self) -> dict:
        return asdict(self)


def send_smtp(settings: Settings, mail: OutgoingEmail) -> None:
    msg = EmailMessage()
    msg["From"] = settings.mail_from
    msg["To"] = mail.to
    msg["Subject"] = mail.subject
    msg.set_content(mail.text)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_username and settings.smtp_password:
            smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
        smtp.send_message(msg)


def queue_email(mail: OutgoingEmail) -> None:
    from app.worker.tasks import send_email

    send_email.delay(mail.to_dict())
