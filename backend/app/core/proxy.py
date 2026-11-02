"""Serverless deployment: the API is reached only through the Next.js proxy on the public domain.

The proxy adds a shared secret and the client IP it received from the platform's edge. Direct calls to the
API's own URL are refused, so the client-IP header (used by the rate limits) cannot be forged.
"""

import hmac

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

PROXY_SECRET_HEADER = "x-studentdocs-proxy-secret"  # noqa: S105 (a header name, not a secret)
CLIENT_IP_HEADER = "x-studentdocs-client-ip"
OPEN_PATHS = frozenset({"/health/live"})


class ProxyGuardMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, secret: str) -> None:
        super().__init__(app)
        self.secret = secret

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path not in OPEN_PATHS:
            given = request.headers.get(PROXY_SECRET_HEADER, "")
            if not given or not hmac.compare_digest(given, self.secret):
                return JSONResponse(
                    {"error": {"code": "not_found", "message": "Not found", "details": None}}, status_code=404
                )
            request.state.proxied = True
        return await call_next(request)
