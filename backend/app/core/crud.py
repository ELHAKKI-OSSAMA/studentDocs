"""Shared persistence helpers: 404 lookup, integrity errors → 409, simple pagination."""

import uuid
from typing import Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel, Field
from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import Base
from app.core.errors import AppError, ConflictError, NotFoundError

M = TypeVar("M", bound=Base)
T = TypeVar("T")

UNIQUE_VIOLATION = "23505"
FOREIGN_KEY_VIOLATION = "23503"
CHECK_VIOLATION = "23514"


def _sqlstate(exc: IntegrityError) -> str | None:
    orig = exc.orig
    return getattr(orig, "sqlstate", None) or getattr(getattr(orig, "__cause__", None), "sqlstate", None)


async def commit_or_conflict(db: AsyncSession) -> None:
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        state = _sqlstate(exc)
        if state == UNIQUE_VIOLATION:
            raise ConflictError.of(
                409, "already_exists", "An entry with the same code already exists"
            ) from exc
        if state == FOREIGN_KEY_VIOLATION:
            raise ConflictError.of(
                409, "in_use", "This entry is referenced by other data; deactivate it instead"
            ) from exc
        if state == CHECK_VIOLATION:
            raise AppError.of(422, "constraint_violation", "Invalid value") from exc
        raise


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class PageParams(BaseModel):
    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


async def paginate(db: AsyncSession, stmt: Select, params: PageParams) -> tuple[list[Any], int]:
    total = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = (await db.scalars(stmt.limit(params.limit).offset(params.offset))).unique().all()
    return list(rows), int(total or 0)


class CrudService(Generic[M]):
    model: ClassVar[type]
    label: ClassVar[str]

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, obj_id: uuid.UUID) -> M:
        obj = await self.db.get(self.model, obj_id)
        if obj is None:
            raise NotFoundError(f"{self.label} not found")
        return obj

    async def save(self, obj: M) -> M:
        self.db.add(obj)
        await commit_or_conflict(self.db)
        # Reload with the mapper's eager options so relationships are usable outside the session.
        return await self.db.get(self.model, obj.id, populate_existing=True)

    async def delete(self, obj_id: uuid.UUID) -> None:
        obj = await self.get(obj_id)
        await self.db.delete(obj)
        await commit_or_conflict(self.db)

    @staticmethod
    def apply(obj: Any, values: dict[str, Any]) -> None:
        for field, value in values.items():
            setattr(obj, field, value)
