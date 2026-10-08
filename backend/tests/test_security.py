"""CSRF, brute force, rate limiting, session invalidation."""

import uuid

from starlette.requests import Request

from app.auth.cookies import ACCESS_COOKIE
from app.core.clientip import client_ip
from app.users.models import Role
from tests.conftest import PASSWORD, TEST_DOMAIN, csrf


async def test_csrf_required_for_state_changes_with_session_cookies(harness):
    client, _ = await harness.logged_in()
    async with client:
        no_header = await client.patch("/api/v1/auth/me", json={"locale": "en"})
        assert no_header.status_code == 403 and no_header.json()["error"]["code"] == "csrf_failed"

        wrong = await client.patch(
            "/api/v1/auth/me", json={"locale": "en"}, headers={"X-CSRF-Token": "forged"}
        )
        assert wrong.status_code == 403

        logout = await client.post("/api/v1/auth/logout")
        assert logout.status_code == 403  # a cross-site form cannot log the user out either

        ok = await client.patch("/api/v1/auth/me", json={"locale": "en"}, headers=csrf(client))
        assert ok.status_code == 200
        # Safe methods never need the token.
        assert (await client.get("/api/v1/auth/me")).status_code == 200


async def test_account_locks_after_repeated_failures(harness):
    user = await harness.create_user()
    async with harness.client() as client:
        for _ in range(5):
            res = await client.post(
                "/api/v1/auth/login", json={"email": user.email, "password": "Wrong-pass-1"}
            )
            assert res.status_code == 401
        # Locked: even the right password is refused until the lock expires.
        res = await client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
        assert res.status_code == 429
        assert res.json()["error"]["details"]["retry_after"] > 0
    # From another IP too: the lock is per account, not per IP.
    async with harness.client() as other:
        res = await other.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
        assert res.status_code == 429


async def test_login_rate_limited_per_ip(make_settings, harness_for):
    strict = make_settings(rate_limit_login_per_ip=3, redis_key_prefix=f"test:{uuid.uuid4().hex}:")
    async for h in harness_for(strict):
        await h.ensure_domain()
        async with h.client(ip="10.9.9.9") as client:
            codes = [
                (
                    await client.post(
                        "/api/v1/auth/login", json={"email": f"x{i}@{TEST_DOMAIN}", "password": "x"}
                    )
                ).status_code
                for i in range(4)
            ]
        assert codes == [401, 401, 401, 429]
        async with h.client(ip="10.9.9.10") as other_ip:
            res = await other_ip.post(
                "/api/v1/auth/login", json={"email": f"y@{TEST_DOMAIN}", "password": "x"}
            )
            assert res.status_code == 401


async def test_registration_rate_limited_per_ip(make_settings, harness_for):
    strict = make_settings(rate_limit_register_per_ip=2, redis_key_prefix=f"test:{uuid.uuid4().hex}:")
    async for h in harness_for(strict):
        await h.ensure_domain()
        async with h.client() as client:
            codes = []
            for _ in range(3):
                body = {
                    "email": f"rl-{uuid.uuid4().hex[:8]}@{TEST_DOMAIN}",
                    "password": PASSWORD,
                    "first_name": "A",
                    "last_name": "B",
                }
                codes.append((await client.post("/api/v1/auth/register", json=body)).status_code)
        assert codes == [202, 202, 429]


async def test_logout_all_invalidates_every_session(harness):
    user = await harness.create_user()
    first = harness.client()
    second = harness.client()
    async with first, second:
        for c in (first, second):
            res = await c.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
            assert res.status_code == 200
        assert (await first.post("/api/v1/auth/logout-all", headers=csrf(first))).status_code == 204
        assert (await second.get("/api/v1/auth/me")).status_code == 401
        assert (await second.post("/api/v1/auth/refresh", headers=csrf(second))).status_code == 401


async def test_deactivation_takes_effect_immediately(harness):
    super_client, _ = await harness.logged_in(Role.SUPER_ADMIN)
    student_client, student = await harness.logged_in()
    async with super_client, student_client:
        res = await super_client.patch(
            f"/api/v1/admin/users/{student.id}", json={"is_active": False}, headers=csrf(super_client)
        )
        assert res.status_code == 200 and res.json()["is_active"] is False
        assert (await student_client.get("/api/v1/auth/me")).status_code == 401
        refresh = await student_client.post("/api/v1/auth/refresh", headers=csrf(student_client))
        assert refresh.status_code == 401


async def test_tampered_access_token_is_rejected(harness):
    client, _ = await harness.logged_in()
    async with client:
        token = client.cookies.get(ACCESS_COOKIE)
        header, payload, signature = token.split(".")
        client.cookies.set(ACCESS_COOKIE, f"{header}.{payload}.{signature[::-1]}", path="/api")
        assert (await client.get("/api/v1/auth/me")).status_code == 401


def _request(peer: str, xff: str | None) -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "client": (peer, 1234), "headers": headers})


def test_forwarded_for_is_only_trusted_from_known_proxies():
    trusted = ["172.16.0.0/12"]
    assert client_ip(_request("172.18.0.5", "1.2.3.4"), trusted) == "1.2.3.4"
    # A client cannot spoof its IP by sending the header directly.
    assert client_ip(_request("8.8.8.8", "1.2.3.4"), trusted) == "8.8.8.8"
    # Only the right-most (proxy-appended) entry counts.
    assert client_ip(_request("172.18.0.5", "6.6.6.6, 1.2.3.4"), trusted) == "1.2.3.4"
    assert client_ip(_request("172.18.0.5", "garbage"), trusted) == "172.18.0.5"


def test_access_token_tolerates_small_clock_adjustments():
    """A token issued "slightly in the future" (clock stepped back after issuance) stays valid."""
    import time

    import jwt

    from app.core.security import JWT_ALGORITHM, decode_access_token

    now = int(time.time())
    claims = {"sub": str(uuid.uuid4()), "type": "access", "jti": "j", "iat": now + 2, "exp": now + 60}
    assert decode_access_token(jwt.encode(claims, "k" * 32, algorithm=JWT_ALGORITHM), "k" * 32) is not None
    claims["iat"] = now + 120  # far in the future: still refused
    assert decode_access_token(jwt.encode(claims, "k" * 32, algorithm=JWT_ALGORITHM), "k" * 32) is None
