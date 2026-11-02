import asyncio
import logging

from botocore.client import BaseClient
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["health"])

CHECK_TIMEOUT_SECONDS = 3


async def check_database(engine: AsyncEngine) -> bool:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return True


async def check_redis(redis: Redis) -> bool:
    return bool(await redis.ping())


async def check_storage(s3: BaseClient, bucket: str) -> bool:
    await asyncio.to_thread(s3.head_bucket, Bucket=bucket)
    return True


async def check_antivirus(host: str, port: int) -> bool:
    from app.documents.scanner import ClamdScanner

    return await asyncio.to_thread(ClamdScanner(host, port, timeout=CHECK_TIMEOUT_SECONDS).ping)


async def _run(name: str, coro) -> tuple[str, bool]:
    try:
        return name, bool(await asyncio.wait_for(coro, CHECK_TIMEOUT_SECONDS))
    except Exception:
        # Details go to logs only; the endpoint never leaks infrastructure errors.
        logger.warning("Health check failed: %s", name, exc_info=True)
        return name, False


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    state = request.app.state
    settings = state.settings
    checks = [
        _run("database", check_database(state.engine)),
        _run("storage", check_storage(state.s3, settings.s3_bucket)),
    ]
    # Only the services this deployment uses (the serverless profile has neither Redis nor ClamAV).
    if state.redis is not None:
        checks.append(_run("redis", check_redis(state.redis)))
    if settings.antivirus == "clamav":
        # Uploads keep working without ClamAV (files wait in SCANNING), but the system is degraded.
        checks.append(_run("antivirus", check_antivirus(settings.clamav_host, settings.clamav_port)))
    results = dict(await asyncio.gather(*checks))
    healthy = all(results.values())
    return JSONResponse(
        {
            "status": "ok" if healthy else "degraded",
            "checks": {k: "ok" if v else "fail" for k, v in results.items()},
        },
        status_code=200 if healthy else 503,
    )
