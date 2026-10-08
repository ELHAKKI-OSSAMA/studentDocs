import hmac

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.auth.cookies import ACCESS_COOKIE, CSRF_COOKIE, CSRF_HEADER, REFRESH_COOKIE

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Endpoints that never act on an existing session (they authenticate from the request body).
CSRF_EXEMPT_PATHS = frozenset(
    {
        "/api/v1/auth/login",
        "/api/v1/auth/register",
        "/api/v1/auth/verify-email",
        "/api/v1/auth/resend-verification",
    }
)


class CsrfMiddleware(BaseHTTPMiddleware):
    """Double-submit cookie check for state-changing requests that carry session cookies."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if (
            request.method not in SAFE_METHODS
            and request.url.path not in CSRF_EXEMPT_PATHS
            and (ACCESS_COOKIE in request.cookies or REFRESH_COOKIE in request.cookies)
        ):
            cookie = request.cookies.get(CSRF_COOKIE, "")
            header = request.headers.get(CSRF_HEADER, "")
            if not cookie or not header or not hmac.compare_digest(cookie, header):
                return JSONResponse(
                    {
                        "error": {
                            "code": "csrf_failed",
                            "message": "Missing or invalid CSRF token",
                            "details": None,
                            "request_id": getattr(request.state, "request_id", None),
                        }
                    },
                    status_code=403,
                )
        return await call_next(request)
