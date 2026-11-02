"""Short-lived keys: fixed-window rate-limit counters and revoked access tokens.

Redis in the Docker stack; a PostgreSQL table in serverless deployments (no Redis there). Both give the
same guarantees: atomic counters, and keys that stop counting once expired.
"""

from datetime import UTC, datetime, timedelta
from typing import Protocol

from redis.asyncio import Redis
from sqlalchemy import BigInteger, DateTime, String, case, delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class EphemeralKey(Base):
    __tablename__ = "ephemeral_keys"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class EphemeralStore(Protocol):
    async def incr_window(self, key: str, window_seconds: int) -> tuple[int, int]:
        """Increments the counter of the current window; returns (count, seconds left)."""
        ...

    async def set_flag(self, key: str, ttl_seconds: int) -> None: ...

    async def has_flag(self, key: str) -> bool: ...

    async def ping(self) -> bool: ...

    async def aclose(self) -> None: ...


class RedisStore:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def incr_window(self, key: str, window_seconds: int) -> tuple[int, int]:
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, window_seconds, nx=True)
            pipe.ttl(key)
            count, _, ttl = await pipe.execute()
        return int(count), int(ttl)

    async def set_flag(self, key: str, ttl_seconds: int) -> None:
        await self.redis.set(key, "1", ex=ttl_seconds)

    async def has_flag(self, key: str) -> bool:
        return bool(await self.redis.exists(key))

    async def ping(self) -> bool:
        return bool(await self.redis.ping())

    async def aclose(self) -> None:
        await self.redis.aclose()


class PostgresStore:
    """One atomic upsert per hit: a new window starts when the stored one has expired."""

    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self.sessionmaker = sessionmaker

    async def incr_window(self, key: str, window_seconds: int) -> tuple[int, int]:
        now = datetime.now(UTC)
        table = EphemeralKey.__table__
        stmt = insert(table).values(key=key, value=1, expires_at=now + timedelta(seconds=window_seconds))
        # In ON CONFLICT DO UPDATE, `table.c` is the stored row and `excluded` the proposed one.
        expired = table.c.expires_at <= now
        stmt = stmt.on_conflict_do_update(
            index_elements=[table.c.key],
            set_={
                "value": case((expired, 1), else_=table.c.value + 1),
                "expires_at": case((expired, stmt.excluded.expires_at), else_=table.c.expires_at),
            },
        ).returning(table.c.value, table.c.expires_at)
        async with self.sessionmaker() as db:
            count, expires_at = (await db.execute(stmt)).one()
            # Housekeeping: drop a few long-expired rows so the table stays small.
            await db.execute(
                delete(table).where(
                    table.c.key.in_(
                        select(table.c.key).where(table.c.expires_at < now - timedelta(hours=1)).limit(50)
                    )
                )
            )
            await db.commit()
        return int(count), max(int((expires_at - now).total_seconds()), 1)

    async def set_flag(self, key: str, ttl_seconds: int) -> None:
        now = datetime.now(UTC)
        stmt = insert(EphemeralKey.__table__).values(
            key=key, value=1, expires_at=now + timedelta(seconds=ttl_seconds)
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["key"], set_={"value": 1, "expires_at": stmt.excluded.expires_at}
        )
        async with self.sessionmaker() as db:
            await db.execute(stmt)
            await db.commit()

    async def has_flag(self, key: str) -> bool:
        async with self.sessionmaker() as db:
            found = await db.scalar(
                select(EphemeralKey.key).where(
                    EphemeralKey.key == key, EphemeralKey.expires_at > datetime.now(UTC)
                )
            )
        return found is not None

    async def ping(self) -> bool:
        async with self.sessionmaker() as db:
            await db.execute(select(1))
        return True

    async def aclose(self) -> None:
        return None
