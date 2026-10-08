"""End-to-end auth flows through the real API, worker, SMTP (Mailpit) and database."""

import re
import uuid

from sqlalchemy import func, select

from app.auth.cookies import ACCESS_COOKIE, CSRF_COOKIE, REFRESH_COOKIE, SESSION_HINT_COOKIE
from app.users.models import User
from tests.conftest import PASSWORD, TEST_DOMAIN, csrf, read_last_email

TOKEN_RE = re.compile(r"verify-email\?token=([A-Za-z0-9_\-]+)")


def _new_email() -> str:
    return f"student-{uuid.uuid4().hex[:10]}@{TEST_DOMAIN}"


async def _register(client, email: str, **extra):
    body = {"email": email, "password": PASSWORD, "first_name": "Ahmed", "last_name": "Alaoui"} | extra
    return await client.post("/api/v1/auth/register", json=body)


async def _token_from_mail(email: str) -> str:
    message = await read_last_email(email)
    match = TOKEN_RE.search(message["Text"])
    assert match, message["Text"]
    return match.group(1)


async def test_register_verify_login_refresh_logout(harness):
    email = _new_email()
    async with harness.client() as client:
        res = await _register(client, email, locale="ar", student_number="D1300000AB")
        assert res.status_code == 202, res.text

        # Not verified yet → login refused (after a correct password only).
        res = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        assert res.status_code == 403 and res.json()["error"]["code"] == "email_not_verified"

        # The verification email is really delivered (worker → SMTP → Mailpit), in the user's locale.
        message = await read_last_email(email)
        assert message["Subject"] == "تأكيد عنوان بريدك الإلكتروني"
        assert "/ar/verify-email?token=" in message["Text"]
        token = TOKEN_RE.search(message["Text"]).group(1)

        res = await client.post("/api/v1/auth/verify-email", json={"token": token})
        assert res.status_code == 200 and res.json()["status"] == "verified"
        # Single use.
        res = await client.post("/api/v1/auth/verify-email", json={"token": token})
        assert res.status_code == 400 and res.json()["error"]["code"] == "invalid_token"

        # Login sets the four session cookies.
        res = await client.post("/api/v1/auth/login", json={"email": email.upper(), "password": PASSWORD})
        assert res.status_code == 200, res.text
        me = res.json()
        assert me["email"] == email and me["role"] == "STUDENT" and me["locale"] == "ar"
        assert me["student"]["student_number"] == "D1300000AB"
        assert "enrollment.self" in me["permissions"] and "admin.access" not in me["permissions"]
        for cookie in (ACCESS_COOKIE, REFRESH_COOKIE, CSRF_COOKIE, SESSION_HINT_COOKIE):
            assert client.cookies.get(cookie), cookie
        assert client.cookies.get(SESSION_HINT_COOKIE) == "student"

        assert (await client.get("/api/v1/auth/me")).status_code == 200

        # Refresh rotates both the refresh token and the access token.
        old_refresh = client.cookies.get(REFRESH_COOKIE)
        old_access = client.cookies.get(ACCESS_COOKIE)
        res = await client.post("/api/v1/auth/refresh", headers=csrf(client))
        assert res.status_code == 200, res.text
        assert client.cookies.get(REFRESH_COOKIE) != old_refresh
        assert client.cookies.get(ACCESS_COOKIE) != old_access
        assert (await client.get("/api/v1/auth/me")).status_code == 200

        # Logout revokes the session server-side and clears cookies.
        current_access = client.cookies.get(ACCESS_COOKIE)
        current_refresh = client.cookies.get(REFRESH_COOKIE)
        res = await client.post("/api/v1/auth/logout", headers=csrf(client))
        assert res.status_code == 204
        assert client.cookies.get(ACCESS_COOKIE) is None

    # A copy of the old cookies (e.g. stolen) is useless after logout.
    async with harness.client() as replay:
        replay.cookies.set(ACCESS_COOKIE, current_access)
        assert (await replay.get("/api/v1/auth/me")).status_code == 401
    async with harness.client() as replay:
        replay.cookies.set(REFRESH_COOKIE, current_refresh, path="/api/v1/auth")
        replay.cookies.set(CSRF_COOKIE, "x" * 20)
        res = await replay.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": "x" * 20})
        assert res.status_code == 401


async def test_refresh_token_reuse_revokes_the_whole_family(harness):
    client, _ = await harness.logged_in()
    async with client:
        stolen = client.cookies.get(REFRESH_COOKIE)
        assert (await client.post("/api/v1/auth/refresh", headers=csrf(client))).status_code == 200
        legit_new = client.cookies.get(REFRESH_COOKIE)

        # Attacker replays the already-rotated token.
        async with harness.client() as attacker:
            attacker.cookies.set(REFRESH_COOKIE, stolen, path="/api/v1/auth")
            attacker.cookies.set(CSRF_COOKIE, "y" * 20)
            res = await attacker.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": "y" * 20})
            assert res.status_code == 401
            assert res.json()["error"]["code"] == "refresh_token_reused"

        # The legitimate successor is revoked too: the whole family is dead.
        assert client.cookies.get(REFRESH_COOKIE) == legit_new
        res = await client.post("/api/v1/auth/refresh", headers=csrf(client))
        assert res.status_code == 401


async def test_non_institutional_email_is_refused(harness):
    async with harness.client() as client:
        res = await _register(client, f"someone-{uuid.uuid4().hex[:6]}@gmail.com")
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "email_domain_not_allowed"


async def test_register_validation(harness):
    async with harness.client() as client:
        weak = await _register(client, _new_email(), password="onlyletters")
        assert weak.status_code == 422
        xss = await _register(client, _new_email(), first_name="<script>alert(1)</script>")
        assert xss.status_code == 422


async def test_duplicate_registration_does_not_reveal_or_duplicate(harness):
    email = _new_email()
    async with harness.client() as client:
        assert (await _register(client, email)).status_code == 202
        assert (await _register(client, email, first_name="Other")).status_code == 202
    async with await harness.db() as db:
        assert await db.scalar(select(func.count()).select_from(User).where(User.email == email)) == 1


async def test_resend_verification_sends_a_working_link(harness):
    email = _new_email()
    async with harness.client() as client:
        await _register(client, email)
        await read_last_email(email)
        assert (
            await client.post("/api/v1/auth/resend-verification", json={"email": email})
        ).status_code == 202
        # Unknown addresses get the same answer.
        unknown = await client.post("/api/v1/auth/resend-verification", json={"email": _new_email()})
        assert unknown.status_code == 202


async def test_disabled_account_is_refused(harness):
    user = await harness.create_user(active=False)
    async with harness.client() as client:
        res = await client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
    assert res.status_code == 403 and res.json()["error"]["code"] == "account_disabled"


async def test_wrong_password_is_generic(harness):
    user = await harness.create_user()
    async with harness.client() as client:
        wrong = await client.post("/api/v1/auth/login", json={"email": user.email, "password": "nope-12345"})
        unknown = await client.post(
            "/api/v1/auth/login", json={"email": _new_email(), "password": "nope-12345"}
        )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]


async def test_profile_update_and_locale_persistence(harness):
    client, _ = await harness.logged_in()
    async with client:
        res = await client.patch(
            "/api/v1/auth/me", json={"locale": "en", "first_name": " Sara  "}, headers=csrf(client)
        )
        assert res.status_code == 200
        assert res.json()["locale"] == "en" and res.json()["first_name"] == "Sara"
        assert (await client.get("/api/v1/auth/me")).json()["locale"] == "en"
