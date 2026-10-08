import asyncio

from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from app.core.db import Base
from app.models import load_all_models
from tests.conftest import alembic_config


async def _scalar_list(url: str, sql: str) -> list[str]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            return list((await conn.execute(text(sql))).scalars())
    finally:
        await engine.dispose()


def _run(coro):
    return asyncio.run(coro)


def test_upgrade_downgrade_roundtrip(settings):
    cfg = alembic_config(settings.database_url)
    command.upgrade(cfg, "head")
    exts = _run(_scalar_list(settings.database_url, "SELECT extname FROM pg_extension"))
    assert {"pgcrypto", "citext", "pg_trgm"} <= set(exts)

    command.downgrade(cfg, "base")
    funcs = _run(
        _scalar_list(
            settings.database_url,
            "SELECT proname FROM pg_proc WHERE proname IN ('set_updated_at', 'forbid_modification')",
        )
    )
    assert funcs == []

    command.upgrade(cfg, "head")
    version = _run(_scalar_list(settings.database_url, "SELECT version_num FROM alembic_version"))
    assert len(version) == 1


def test_models_and_migrations_are_in_sync(settings):
    command.upgrade(alembic_config(settings.database_url), "head")
    load_all_models()

    async def diff():
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                return await conn.run_sync(
                    lambda sync_conn: compare_metadata(MigrationContext.configure(sync_conn), Base.metadata)
                )
        finally:
            await engine.dispose()

    assert _run(diff()) == [], "ORM models differ from migrations: run `alembic revision --autogenerate`"
