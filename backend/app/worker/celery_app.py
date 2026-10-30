from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery("studentdocs", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    result_expires=3600,
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    # Scans, inbound email and AI have their own queues: a slow model never delays antivirus scans.
    task_routes={
        "documents.scan": {"queue": settings.scan_queue},
        "email.poll": {"queue": settings.email_queue},
        "email.process": {"queue": settings.email_queue},
        "email.sweep": {"queue": settings.email_queue},
        "email.extract": {"queue": settings.ai_queue},
    },
    # Periodic jobs (run by the single `beat` service).
    beat_schedule={
        "email-poll": {"task": "email.poll", "schedule": float(settings.email_poll_seconds)},
        "email-sweep": {"task": "email.sweep", "schedule": 300.0},
    },
    # A scan never runs forever: clamd has its own socket timeout, this is the hard stop.
    task_time_limit=int(settings.clamav_timeout_seconds * 3),
)
celery_app.autodiscover_tasks(["app.worker"])
