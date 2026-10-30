"""Integration tests run against real PostgreSQL / Redis / S3 / Mailpit (see docker-compose.yml).

TEST_DATABASE_URL must point at a dedicated database: it is reset (downgrade base → upgrade head) per run.
"""

import asyncio
import os
import random
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
import pytest
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from httpx._client import ClientState

from alembic import command
from app.auth.cookies import CSRF_COOKIE
from app.core.config import Settings
from app.core.security import hash_password
from app.main import create_app
from app.students.models import Student
from app.users.models import AllowedEmailDomain, AuthIdentity, IdentityProvider, Role, User

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_DOMAIN = "test-univ.ma"
PASSWORD = "Passw0rd-test-123"
MAILPIT_API_URL = os.environ.get("MAILPIT_API_URL", "http://localhost:8025")
SESSION_PREFIX = f"test:{uuid.uuid4().hex[:8]}:"
# Dedicated Celery queues: the stack's own worker (main database) never consumes test tasks.
SCAN_QUEUE = f"test-documents-{uuid.uuid4().hex[:8]}"
EMAIL_QUEUE = f"test-email-{uuid.uuid4().hex[:8]}"
AI_QUEUE = f"test-ai-{uuid.uuid4().hex[:8]}"
# GreenMail (SMTP + IMAP test server, docker-compose.test.yml) and the in-process scripted LLM server.
GREENMAIL_HOST = os.environ.get("GREENMAIL_HOST", "greenmail")
TRUSTED_AUTHSERV_ID = "mx.test-univ.ma"
LLM_SERVER: dict = {}


def _test_settings(**overrides) -> Settings:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.exit("TEST_DATABASE_URL is not set; refusing to run tests against the main database", 2)
    values = {
        "app_env": "test",
        "database_url": database_url,
        "secret_key": "test-secret-key-0123456789-abcdefghijklmnop",
        "log_level": "WARNING",
        "trusted_proxies": ["127.0.0.1/32"],
        "redis_key_prefix": SESSION_PREFIX,
        # Generous defaults; brute-force tests build apps with strict limits.
        "rate_limit_login_per_ip": 1000,
        "rate_limit_register_per_ip": 1000,
        "scan_queue": SCAN_QUEUE,
        "scan_max_retries": 1,
        "scan_retry_base_seconds": 1,
        # Inbound email: GreenMail, plain IMAP (test server only); one mailbox per test (imap_username).
        "imap_host": GREENMAIL_HOST,
        "imap_port": 3143,
        "imap_ssl": False,
        "imap_username": "unused@test-univ.ma",
        "imap_password": "greenmail-test-only",
        "imap_timeout_seconds": 10,
        "email_trusted_authserv_ids": [TRUSTED_AUTHSERV_ID],
        "email_queue": EMAIL_QUEUE,
        "email_process_max_retries": 1,
        # AI: the scripted local server (loopback = local provider), short timeout, one retry.
        "ai_provider": "openai_compatible",
        "ai_base_url": LLM_SERVER.get("url", "http://127.0.0.1:9/v1"),
        "ai_model": "studentdocs-test-model",
        "ai_timeout_seconds": 3,
        "ai_max_retries": 1,
        "ai_queue": AI_QUEUE,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture(scope="session")
def llm_server():
    """Scripted OpenAI-compatible server on the loopback interface (tests/support/llm_server.py)."""
    import threading

    from tests.support import llm_server as module

    server = module.serve("127.0.0.1", 0)
    LLM_SERVER["url"] = f"http://127.0.0.1:{server.server_address[1]}/v1"
    LLM_SERVER["received"] = module.RECEIVED
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield LLM_SERVER
    server.shutdown()


@pytest.fixture(scope="session")
def settings(llm_server) -> Settings:
    return _test_settings()


@pytest.fixture
def make_settings():
    return _test_settings


def alembic_config(database_url: str) -> Config:
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    cfg.attributes["database_url"] = database_url
    return cfg


@pytest.fixture(scope="session")
def migrated_db(settings: Settings) -> str:
    cfg = alembic_config(settings.database_url)
    command.downgrade(cfg, "base")  # fresh schema and data for every run
    command.upgrade(cfg, "head")
    return settings.database_url


@pytest.fixture(scope="session", autouse=True)
def scan_worker(settings: Settings, migrated_db: str):
    """A real Celery worker (real Redis broker, real ClamAV, test database) consuming the test queue."""
    from celery.contrib.testing.worker import start_worker

    from app.worker import context
    from app.worker.celery_app import celery_app

    context.configure(settings)
    with start_worker(
        celery_app,
        pool="threads",
        concurrency=2,
        perform_ping_check=False,
        queues=[settings.scan_queue, settings.email_queue, settings.ai_queue],
        shutdown_timeout=30,
    ) as worker:
        yield worker


class ReusableClient(AsyncClient):
    """AsyncClient that may be used (e.g. to log in) before entering `async with`."""

    async def __aenter__(self):
        if self._state == ClientState.OPENED:
            return self
        return await super().__aenter__()


def random_ip() -> str:
    return f"10.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"  # noqa: S311


@dataclass
class Harness:
    """A running app plus helpers to create clients (one cookie jar per simulated browser)."""

    app: FastAPI

    def client(self, ip: str | None = None) -> AsyncClient:
        return ReusableClient(
            transport=ASGITransport(app=self.app),
            base_url="http://testserver",
            headers={"X-Forwarded-For": ip or random_ip()},
        )

    async def db(self):
        return self.app.state.sessionmaker()

    async def ensure_domain(self, domain: str = TEST_DOMAIN) -> None:
        async with self.app.state.sessionmaker() as db:
            from sqlalchemy import select

            if not await db.scalar(select(AllowedEmailDomain).where(AllowedEmailDomain.domain == domain)):
                db.add(AllowedEmailDomain(domain=domain, is_active=True))
                await db.commit()

    async def create_user(
        self,
        role: Role = Role.STUDENT,
        *,
        verified: bool = True,
        active: bool = True,
        email: str | None = None,
    ) -> User:
        email = email or f"{role.value.lower()}-{uuid.uuid4().hex[:10]}@{TEST_DOMAIN}"
        async with self.app.state.sessionmaker() as db:
            user = User(
                email=email,
                role=role,
                first_name="Test",
                last_name=role.value.title(),
                password_hash=hash_password(PASSWORD),
                is_active=active,
                failed_login_count=0,
                email_verified_at=datetime.now(UTC) if verified else None,
            )
            user.identities.append(AuthIdentity(provider=IdentityProvider.LOCAL, subject=email))
            db.add(user)
            await db.flush()
            if role == Role.STUDENT:
                db.add(Student(user_id=user.id))
            await db.commit()
            return user

    async def logged_in(self, role: Role = Role.STUDENT, **kwargs) -> tuple[AsyncClient, User]:
        user = await self.create_user(role, **kwargs)
        client = self.client()
        res = await client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
        assert res.status_code == 200, res.text
        return client, user


def csrf(client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get(CSRF_COOKIE, "")}


async def _harness_for(settings: Settings) -> AsyncIterator[Harness]:
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        yield Harness(app)


@pytest.fixture
async def harness(settings: Settings, migrated_db: str) -> AsyncIterator[Harness]:
    async for h in _harness_for(settings):
        await h.ensure_domain()
        yield h


@pytest.fixture
def harness_for(migrated_db: str):
    """Builds a harness with custom settings (e.g. strict rate limits)."""
    return _harness_for


@pytest.fixture
async def client(harness: Harness) -> AsyncIterator[AsyncClient]:
    async with harness.client() as c:
        yield c


async def read_last_email(to: str, wait_seconds: float = 20.0) -> dict:
    """Waits for the worker to deliver a message to Mailpit and returns it (real SMTP round-trip)."""
    deadline = asyncio.get_running_loop().time() + wait_seconds
    async with httpx.AsyncClient(base_url=MAILPIT_API_URL, timeout=5) as mp:
        while True:
            res = await mp.get("/api/v1/search", params={"query": f'to:"{to}"', "limit": 1})
            res.raise_for_status()
            messages = res.json().get("messages", [])
            if messages:
                full = await mp.get(f"/api/v1/message/{messages[0]['ID']}")
                full.raise_for_status()
                return full.json()
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError(f"No email delivered to {to} within {wait_seconds}s")
            await asyncio.sleep(0.3)


async def count_emails(to: str) -> int:
    async with httpx.AsyncClient(base_url=MAILPIT_API_URL, timeout=5) as mp:
        res = await mp.get("/api/v1/search", params={"query": f'to:"{to}"'})
        res.raise_for_status()
        return int(res.json().get("messages_count", 0))
