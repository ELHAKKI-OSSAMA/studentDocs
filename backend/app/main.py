from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from app.academic.router import admin_router as admin_catalog_router
from app.academic.router import public_router as catalog_router
from app.admin.router import router as admin_router
from app.auth.router import router as auth_router
from app.core import health
from app.core.config import Settings, get_settings
from app.core.csrf import CsrfMiddleware
from app.core.db import create_engine, create_sessionmaker
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.storage import create_s3_client
from app.documents.scanning import celery_scan_queue
from app.documents.service import DocumentPipeline
from app.documents.storage import ObjectStorage
from app.emails.cases import celery_email_queue
from app.emails.router import router as admin_emails_router
from app.mailconfig.router import router as smtp_settings_router
from app.notifications.router import router as notifications_router
from app.requests.admin_router import router as admin_requests_router
from app.requests.router import router as requests_router
from app.students.router import admin_router as admin_students_router
from app.students.router import enrollments_admin_router
from app.students.router import router as students_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        app.state.engine = create_engine(settings.database_url)
        app.state.sessionmaker = create_sessionmaker(app.state.engine)
        app.state.redis = Redis.from_url(settings.redis_url)
        app.state.s3 = create_s3_client(settings)
        app.state.storage = ObjectStorage(app.state.s3, settings.s3_bucket, settings.storage_tenant)
        app.state.documents = DocumentPipeline(app.state.storage, celery_scan_queue(settings.scan_queue))
        app.state.email_tasks = celery_email_queue(settings.email_queue, settings.ai_queue)
        try:
            yield
        finally:
            await app.state.redis.aclose()
            await app.state.engine.dispose()

    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
        # Interactive docs are disabled in production to reduce the exposed surface.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    # Starlette runs the last-added middleware first: CORS → request context → CSRF → routes.
    app.add_middleware(CsrfMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID"],
    )
    register_error_handlers(app)
    app.include_router(health.router)
    for router in (
        auth_router,
        catalog_router,
        students_router,
        admin_router,
        admin_catalog_router,
        admin_students_router,
        enrollments_admin_router,
        requests_router,
        admin_requests_router,
        admin_emails_router,
        smtp_settings_router,
        notifications_router,
    ):
        app.include_router(router)
    return app
