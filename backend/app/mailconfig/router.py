import asyncio

from fastapi import APIRouter, Request

from app.audit.service import record
from app.auth.dependencies import Requires
from app.auth.permissions import Perm
from app.core.deps import ClientIp, DbSession
from app.core.errors import AppError
from app.mailconfig.models import SmtpSettings
from app.mailconfig.schemas import SmtpSettingsIn, SmtpSettingsOut, SmtpTestIn, SmtpTestResult
from app.mailconfig.service import (
    SINGLETON_ID,
    SmtpSettingsService,
    effective_config,
    readable,
    row_config,
    send_test,
)
from app.users.models import User

router = APIRouter(prefix="/api/v1/admin/settings/smtp", tags=["admin-settings"])

SettingsManager = Requires(Perm.ADMIN_ACCESS, Perm.SETTINGS_MANAGE)


async def _out(db, settings, row: SmtpSettings | None) -> SmtpSettingsOut:
    active = await effective_config(db, settings)
    updated_by = await db.get(User, row.updated_by_id) if row and row.updated_by_id else None
    return SmtpSettingsOut(
        configured=row is not None,
        is_enabled=bool(row and row.is_enabled),
        host=row.host if row else None,
        port=row.port if row else None,
        security=row.security if row else None,
        username=row.username if row else None,
        has_password=bool(row and row.password_encrypted),
        password_readable=readable(settings, row) if row else True,
        mail_from=row.mail_from if row else None,
        updated_at=row.updated_at if row else None,
        updated_by_name=f"{updated_by.first_name} {updated_by.last_name}" if updated_by else None,
        active_source=active.source,
        environment_host=settings.smtp_host,
        environment_port=settings.smtp_port,
        database_settings_allowed=settings.smtp_use_database_settings,
    )


@router.get("", response_model=SmtpSettingsOut)
async def get_smtp_settings(request: Request, db: DbSession, _: SettingsManager):
    settings = request.app.state.settings
    return await _out(db, settings, await SmtpSettingsService(db, settings).get())


@router.put("", response_model=SmtpSettingsOut)
async def save_smtp_settings(
    data: SmtpSettingsIn, request: Request, db: DbSession, current: SettingsManager, ip: ClientIp
):
    settings = request.app.state.settings
    if data.username and not data.password and not data.clear_password:
        row = await SmtpSettingsService(db, settings).get()
        if row is None or not row.password_encrypted:
            raise AppError.of(422, "smtp_password_required", "A password is required with a username")
    row = await SmtpSettingsService(db, settings).save(data, current.user, ip)
    return await _out(db, settings, row)


@router.post("/test", response_model=SmtpTestResult)
async def test_smtp_settings(
    data: SmtpTestIn, request: Request, db: DbSession, current: SettingsManager, ip: ClientIp
):
    """Sends one email with the configuration as typed (saved password used when none is typed)."""
    settings = request.app.state.settings
    service = SmtpSettingsService(db, settings)
    stored = await service.get()
    candidate = service.candidate(data, stored)
    config = row_config(settings, candidate)
    if config.username and not config.password:
        raise AppError.of(422, "smtp_password_required", "A password is required with a username")
    error = await asyncio.to_thread(send_test, config, str(data.to))
    record(
        db,
        actor_id=current.id,
        action="SMTP_SETTINGS_TESTED",
        entity="smtp_settings",
        entity_id=SINGLETON_ID,
        ip=ip,
        details={"host": data.host, "port": data.port, "ok": error is None, "error": error},
    )
    await db.commit()
    return SmtpTestResult(
        ok=error is None,
        error=error,
        used_stored_password=bool(config.password) and not data.password,
    )
