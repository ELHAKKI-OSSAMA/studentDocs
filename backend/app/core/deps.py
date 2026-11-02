from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clientip import client_ip
from app.core.config import Settings
from app.core.ephemeral import EphemeralStore
from app.core.ratelimit import RateLimiter
from app.documents.service import DocumentPipeline
from app.documents.storage import ObjectStorage


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


def get_ephemeral(request: Request) -> EphemeralStore:
    return request.app.state.ephemeral


def get_rate_limiter(request: Request) -> RateLimiter:
    return RateLimiter(request.app.state.ephemeral, request.app.state.settings.redis_key_prefix)


def get_storage(request: Request) -> ObjectStorage:
    return request.app.state.storage


def get_documents(request: Request) -> DocumentPipeline:
    return request.app.state.documents


def get_client_ip(request: Request) -> str:
    return client_ip(request, request.app.state.settings.trusted_proxies)


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
DbSession = Annotated[AsyncSession, Depends(get_db)]
EphemeralDep = Annotated[EphemeralStore, Depends(get_ephemeral)]
RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]
ClientIp = Annotated[str, Depends(get_client_ip)]
StorageDep = Annotated[ObjectStorage, Depends(get_storage)]
DocumentsDep = Annotated[DocumentPipeline, Depends(get_documents)]
