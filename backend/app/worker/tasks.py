from app.core.config import get_settings
from app.core.mailer import OutgoingEmail, send_smtp
from app.worker.celery_app import celery_app


@celery_app.task(name="system.ping")
def ping() -> str:
    """Round-trip check used by the worker health verification."""
    return "pong"


@celery_app.task(
    name="mail.send",
    autoretry_for=(OSError,),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=8,
)
def send_email(mail: dict) -> None:
    send_smtp(get_settings(), OutgoingEmail(**mail))
