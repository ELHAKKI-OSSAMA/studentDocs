"""SMTP relay configured by a super-admin: secret handling, test send, and use by the real mail worker."""

import asyncio
import uuid

import pytest
from sqlalchemy import delete, select

from app.audit.models import AuditLog
from app.mailconfig.models import SmtpSettings
from app.mailconfig.service import effective_config
from app.users.models import Role
from app.worker.tasks import send_email
from tests.conftest import csrf, read_last_email

PATH = "/api/v1/admin/settings/smtp"
MAILPIT = {"host": "mailpit", "port": 1025, "security": "NONE", "username": None}


@pytest.fixture
async def setup(harness):
    async with harness.app.state.sessionmaker() as db:
        await db.execute(delete(SmtpSettings))
        await db.commit()
    superadmin, _ = await harness.logged_in(Role.SUPER_ADMIN)
    admin, _ = await harness.logged_in(Role.ADMIN)
    async with superadmin, admin:
        yield harness, superadmin, admin
    async with harness.app.state.sessionmaker() as db:
        await db.execute(delete(SmtpSettings))
        await db.commit()


def _mailbox() -> str:
    return f"smtp-{uuid.uuid4().hex[:10]}@test-univ.ma"


async def test_only_super_admin_manages_smtp(setup):
    _, superadmin, admin = setup
    assert (await admin.get(PATH)).status_code == 403
    res = await admin.put(
        PATH, json={**MAILPIT, "is_enabled": True, "mail_from": "x@y.ma"}, headers=csrf(admin)
    )
    assert res.status_code == 403
    body = (await superadmin.get(PATH)).json()
    assert body["configured"] is False and body["active_source"] == "environment"


async def test_password_is_encrypted_and_never_returned(setup):
    h, superadmin, _ = setup
    payload = {
        "is_enabled": False,
        "host": "smtp.example.org",
        "port": 465,
        "security": "SSL",
        "username": "relay@example.org",
        "password": "app-password-1234",
        "mail_from": "StudentDocs <relay@example.org>",
    }
    res = await superadmin.put(PATH, json=payload, headers=csrf(superadmin))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["has_password"] and body["password_readable"] and "app-password-1234" not in res.text
    # Disabled: the .env relay stays active.
    assert body["active_source"] == "environment"

    async with h.app.state.sessionmaker() as db:
        row = await db.get(SmtpSettings, 1)
        assert row.password_encrypted and "app-password-1234" not in row.password_encrypted
        audit = (await db.scalars(select(AuditLog).where(AuditLog.action == "SMTP_SETTINGS_UPDATED"))).all()[
            -1
        ]
        assert "app-password-1234" not in str(audit.details) and audit.details["password_changed"]

    # Saving again without a password keeps the stored one; a username without any password is refused.
    res = await superadmin.put(PATH, json={**payload, "password": None}, headers=csrf(superadmin))
    assert res.json()["has_password"]
    res = await superadmin.put(
        PATH, json={**payload, "password": None, "clear_password": True}, headers=csrf(superadmin)
    )
    assert res.json()["has_password"] is False
    res = await superadmin.put(PATH, json={**payload, "password": None}, headers=csrf(superadmin))
    assert res.status_code == 422 and res.json()["error"]["code"] == "smtp_password_required"
    # A password without a username would never be used to log in: refused.
    res = await superadmin.put(PATH, json={**payload, "username": ""}, headers=csrf(superadmin))
    assert res.status_code == 422
    # Header injection in the sender is rejected.
    res = await superadmin.put(
        PATH, json={**payload, "mail_from": "a@b.ma\r\nBcc: x@y.ma"}, headers=csrf(superadmin)
    )
    assert res.status_code == 422


async def test_test_send_and_worker_use_the_saved_relay(setup):
    h, superadmin, _ = setup
    to = _mailbox()
    form = {**MAILPIT, "is_enabled": True, "mail_from": "Relais Admin <relais@test-univ.ma>"}

    # Test with the typed (unsaved) configuration: really delivered to Mailpit.
    res = await superadmin.post(f"{PATH}/test", json={**form, "to": to}, headers=csrf(superadmin))
    assert res.status_code == 200 and res.json() == {"ok": True, "error": None, "used_stored_password": False}
    mail = await read_last_email(to)
    assert "test SMTP" in mail["Subject"] and mail["From"]["Address"] == "relais@test-univ.ma"

    # Unreachable relay: a clean error code, no exception text.
    res = await superadmin.post(f"{PATH}/test", json={**form, "port": 9, "to": to}, headers=csrf(superadmin))
    assert res.json()["ok"] is False and res.json()["error"] == "smtp_connection_failed"

    # Saved and enabled: the application's own emails (Celery mail.send) go through it.
    res = await superadmin.put(PATH, json=form, headers=csrf(superadmin))
    assert res.json()["active_source"] == "database"
    async with h.app.state.sessionmaker() as db:
        assert (await effective_config(db, h.app.state.settings)).mail_from == form["mail_from"]
    other = _mailbox()
    # The real mail.send task body, run by this process's worker context (test database).
    await asyncio.to_thread(
        send_email.apply, args=[{"to": other, "subject": "Notification", "text": "Bonjour"}]
    )
    mail = await read_last_email(other)
    assert mail["From"]["Address"] == "relais@test-univ.ma"


async def test_test_stacks_ignore_the_saved_relay(setup, make_settings):
    h, superadmin, _ = setup
    form = {**MAILPIT, "is_enabled": True, "mail_from": "Relais <relais@test-univ.ma>"}
    assert (await superadmin.put(PATH, json=form, headers=csrf(superadmin))).status_code == 200
    async with h.app.state.sessionmaker() as db:
        assert (await effective_config(db, h.app.state.settings)).source == "database"
        ignored = make_settings(smtp_use_database_settings=False)
        assert (await effective_config(db, ignored)).source == "environment"
