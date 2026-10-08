from dataclasses import dataclass

from redis.asyncio import Redis

from app.core.errors import AppError


class RateLimitedError(AppError):
    status_code = 429
    code = "rate_limited"


@dataclass(frozen=True)
class RateLimiter:
    """Fixed-window counter in Redis. Atomic (INCR + EXPIRE NX in one transaction)."""

    redis: Redis
    prefix: str

    async def hit(self, scope: str, key: str, *, limit: int, window_seconds: int) -> None:
        redis_key = f"{self.prefix}rl:{scope}:{key}"
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.incr(redis_key)
            pipe.expire(redis_key, window_seconds, nx=True)
            pipe.ttl(redis_key)
            count, _, ttl = await pipe.execute()
        if count > limit:
            raise RateLimitedError(
                "Too many attempts, please retry later", details={"retry_after": max(int(ttl), 1)}
            )
