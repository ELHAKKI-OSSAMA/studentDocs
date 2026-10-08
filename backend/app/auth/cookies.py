"""Session cookies.

- sd_access  : JWT, httpOnly, sent to the whole API.
- sd_refresh : opaque rotating token, httpOnly, sent only to /api/v1/auth.
- sd_csrf    : double-submit token, readable by JS, echoed in the X-CSRF-Token header.
- sd_session : non-secret UI hint ("is someone logged in, and which area") read by the frontend proxy.
"""

from fastapi import Response

from app.core.config import Settings
from app.users.models import Role

ACCESS_COOKIE = "sd_access"
REFRESH_COOKIE = "sd_refresh"
CSRF_COOKIE = "sd_csrf"
SESSION_HINT_COOKIE = "sd_session"
CSRF_HEADER = "x-csrf-token"

API_PATH = "/api"
REFRESH_PATH = "/api/v1/auth"


def set_session_cookies(
    response: Response, settings: Settings, *, access: str, refresh: str, csrf: str, role: Role
) -> None:
    secure = settings.cookie_secure
    refresh_ttl = settings.refresh_token_ttl_seconds
    response.set_cookie(
        ACCESS_COOKIE,
        access,
        max_age=settings.access_token_ttl_seconds,
        path=API_PATH,
        httponly=True,
        secure=secure,
        samesite="lax",
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh,
        max_age=refresh_ttl,
        path=REFRESH_PATH,
        httponly=True,
        secure=secure,
        samesite="strict",
    )
    response.set_cookie(
        CSRF_COOKIE, csrf, max_age=refresh_ttl, path="/", httponly=False, secure=secure, samesite="strict"
    )
    area = "admin" if role in (Role.ADMIN, Role.SUPER_ADMIN) else "student"
    response.set_cookie(
        SESSION_HINT_COOKIE,
        area,
        max_age=refresh_ttl,
        path="/",
        httponly=False,
        secure=secure,
        samesite="lax",
    )


def clear_session_cookies(response: Response, settings: Settings) -> None:
    for name, path in (
        (ACCESS_COOKIE, API_PATH),
        (REFRESH_COOKIE, REFRESH_PATH),
        (CSRF_COOKIE, "/"),
        (SESSION_HINT_COOKIE, "/"),
    ):
        response.delete_cookie(
            name, path=path, secure=settings.cookie_secure, httponly=name in (ACCESS_COOKIE, REFRESH_COOKIE)
        )
