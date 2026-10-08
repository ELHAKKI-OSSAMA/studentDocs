import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict

from app.auth.dependencies import Requires
from app.auth.permissions import Perm
from app.core.crud import Page, PageParams
from app.core.deps import DbSession
from app.notifications.service import NotificationService

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])

Self = Requires(Perm.PROFILE_SELF)


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: str
    request_id: uuid.UUID | None
    reference: str | None
    status: str | None
    created_at: datetime
    read_at: datetime | None


class UnreadCount(BaseModel):
    unread: int


@router.get("", response_model=Page[NotificationOut])
async def my_notifications(
    db: DbSession, current: Self, params: Annotated[PageParams, Depends()], unread_only: bool = False
):
    rows, total = await NotificationService(db).list_for(current.id, params.limit, params.offset, unread_only)
    return Page(
        items=[NotificationOut.model_validate(r) for r in rows],
        total=total,
        limit=params.limit,
        offset=params.offset,
    )


@router.get("/unread-count", response_model=UnreadCount)
async def unread_count(db: DbSession, current: Self):
    return UnreadCount(unread=await NotificationService(db).unread_count(current.id))


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(notification_id: uuid.UUID, db: DbSession, current: Self) -> Response:
    # Scoped to the caller: another user's notification id simply matches nothing.
    await NotificationService(db).mark_read(current.id, notification_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_read(db: DbSession, current: Self) -> Response:
    await NotificationService(db).mark_read(current.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
