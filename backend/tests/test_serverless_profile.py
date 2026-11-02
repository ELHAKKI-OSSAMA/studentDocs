"""Serverless profile (Vercel + Supabase + Brevo): no Redis, no Celery worker, no ClamAV.

Same real PostgreSQL / S3 / Mailpit as the other tests; only the runtime profile changes.
"""

import uuid

import pytest
from sqlalchemy import select

from app.core.ephemeral import EphemeralKey, PostgresStore
from app.documents.models import Document
from app.users.models import Role
from tests.conftest import PASSWORD, TEST_DOMAIN, csrf, read_last_email
from tests.factories import PDF, attachment, make_catalog, make_enrollment, submit

SECRET = "proxy-secret-for-tests-0123456789"
SERVERLESS = {
    "task_mode": "inline",
    "ephemeral_store": "postgres",
    "antivirus": "none",
    "db_pool": "null",
    "proxy_shared_secret": SECRET,
    "imap_host": "",
    "ai_provider": "none",
    "max_upload_bytes": 4 * 1024 * 1024,
}


@pytest.fixture
async def serverless(harness_for, make_settings):
    async for h in harness_for(make_settings(**SERVERLESS)):
        h.headers = {"X-StudentDocs-Proxy-Secret": SECRET}
        await h.ensure_domain()
        # No Redis client and no Celery queue in this profile.
        assert h.app.state.redis is None and h.app.state.email_tasks is None
        yield h


async def test_direct_calls_without_the_proxy_secret_are_refused(serverless):
    h = serverless
    async with h.client() as client:
        client.headers.pop("X-StudentDocs-Proxy-Secret")
        assert (await client.get("/api/v1/catalog/document-types")).status_code == 404
        client.headers["X-StudentDocs-Proxy-Secret"] = "wrong"
        assert (await client.get("/health/ready")).status_code == 404
        # Liveness stays open for the platform's checks.
        assert (await client.get("/health/live")).status_code == 200
    async with h.client() as client:
        ready = (await client.get("/api/v1/health/ready")).json()
        assert set(ready["checks"]) == {"database", "storage"} and ready["status"] == "ok"


async def test_registration_email_is_sent_inline(serverless):
    h = serverless
    email = f"inline-{uuid.uuid4().hex[:10]}@{TEST_DOMAIN}"
    async with h.client() as client:
        res = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": PASSWORD,
                "first_name": "Inès",
                "last_name": "Kabbaj",
                "locale": "fr",
            },
        )
        assert res.status_code in (200, 201, 202), res.text
    # Delivered during the request, without any worker.
    mail = await read_last_email(email, wait_seconds=5)
    assert "verify-email?token=" in mail["Text"]


async def test_rate_limits_and_logout_use_postgres(serverless):
    h = serverless
    user = await h.create_user(Role.ADMIN)
    ip = "203.0.113.77"
    async with h.client(ip) as client:
        for _ in range(3):
            await client.post(
                "/api/v1/auth/login", json={"email": user.email, "password": "wrong-password-1"}
            )
    async with h.app.state.sessionmaker() as db:
        row = await db.scalar(select(EphemeralKey).where(EphemeralKey.key.like(f"%rl:login%{ip}%")))
        # The IP comes from the authenticated proxy header, not from the TCP peer.
        assert row is not None and row.value >= 3

    client, _ = await h.logged_in(Role.ADMIN)
    async with client:
        assert (await client.get("/api/v1/auth/me")).status_code == 200
        access = client.cookies.get("sd_access")
        assert (await client.post("/api/v1/auth/logout", headers=csrf(client))).status_code in (200, 204)
        # The revoked access token (kept in PostgreSQL) is refused even if replayed.
        client.cookies.set("sd_access", access)
        assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_postgres_window_counter_restarts_after_expiry(serverless):
    store = PostgresStore(serverless.app.state.sessionmaker)
    key = f"test:{uuid.uuid4().hex}"
    assert (await store.incr_window(key, 60))[0] == 1
    count, ttl = await store.incr_window(key, 60)
    assert count == 2 and 0 < ttl <= 60
    async with serverless.app.state.sessionmaker() as db:
        row = await db.get(EphemeralKey, key)
        row.expires_at = row.expires_at.replace(year=2000)
        await db.commit()
    assert (await store.incr_window(key, 60))[0] == 1


async def test_uploads_are_accepted_without_antivirus(serverless):
    h = serverless
    cat = await make_catalog(h)
    student, user = await h.logged_in()
    enrollment = await make_enrollment(h, user, cat)
    async with student:
        res = await submit(
            student, enrollment.id, [(cat.with_attachment, 1)], [attachment(cat.with_attachment)]
        )
        assert res.status_code == 201, res.text
        [doc] = res.json()["documents"]
        # No scanner: immediately available, the reason being recorded.
        assert doc["scan_status"] == "CLEAN" and doc["can_download"] is True
        download = await student.get(f"/api/v1/requests/{res.json()['id']}/documents/{doc['id']}/download")
        assert download.status_code == 200 and download.content == PDF
    async with h.app.state.sessionmaker() as db:
        stored = await db.get(Document, uuid.UUID(doc["id"]))
        assert stored.scan_detail == "antivirus_disabled"
