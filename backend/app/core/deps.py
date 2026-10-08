from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clientip import client_ip
from app.core.config import Settings
from app.core.ratelimit import RateLimiter
from app.documents.storage import ObjectStorage


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


def get_redis(request: Request) -> Redis:
    return request.app.state.redis


def get_rate_limiter(request: Request) -> RateLimiter:
    return RateLimiter(request.app.state.redis, request.app.state.settings.redis_key_prefix)


def get_storage(request: Request) -> ObjectStorage:
    return request.app.state.storage


def get_client_ip(request: Request) -> str:
    return client_ip(request, request.app.state.settings.trusted_proxies)


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
DbSession = Annotated[AsyncSession, Depends(get_db)]
RedisDep = Annotated[Redis, Depends(get_redis)]
RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]
ClientIp = Annotated[str, Depends(get_client_ip)]
StorageDep = Annotated[ObjectStorage, Depends(get_storage)]
