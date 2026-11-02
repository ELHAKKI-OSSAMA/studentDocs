from dataclasses import dataclass

from app.core.ephemeral import EphemeralStore
from app.core.errors import AppError


class RateLimitedError(AppError):
    status_code = 429
    code = "rate_limited"


@dataclass(frozen=True)
class RateLimiter:
    """Fixed-window counter (Redis or PostgreSQL, see app.core.ephemeral). Atomic per hit."""

    store: EphemeralStore
    prefix: str

    async def hit(self, scope: str, key: str, *, limit: int, window_seconds: int) -> None:
        count, ttl = await self.store.incr_window(f"{self.prefix}rl:{scope}:{key}", window_seconds)
        if count > limit:
            raise RateLimitedError(
                "Too many attempts, please retry later", details={"retry_after": max(int(ttl), 1)}
            )
