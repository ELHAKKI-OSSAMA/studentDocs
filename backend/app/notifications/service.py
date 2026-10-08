"""NotificationService: in-app channel today; email delivery plugs in here in Phase 5."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.models import Notification
from app.requests.models import Request


class NotificationType:
    REQUEST_RECEIVED = "REQUEST_RECEIVED"
    STATUS_CHANGED = "STATUS_CHANGED"
    INFORMATION_REQUESTED = "INFORMATION_REQUESTED"
    NEW_MESSAGE = "NEW_MESSAGE"
    INFORMATION_PROVIDED = "INFORMATION_PROVIDED"
    REQUEST_ASSIGNED = "REQUEST_ASSIGNED"


class NotificationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def notify(self, user_id: uuid.UUID | None, type_: str, request: Request) -> None:
        """Queues a notification in the caller's transaction. The frontend renders it from type + status."""
        if user_id is None:
            return
        self.db.add(
            Notification(
                user_id=user_id,
                type=type_,
                request_id=request.id,
                reference=request.reference,
                status=request.status.value,
            )
        )

    async def list_for(self, user_id: uuid.UUID, limit: int, offset: int, unread_only: bool):
        stmt = select(Notification).where(Notification.user_id == user_id)
        if unread_only:
            stmt = stmt.where(Notification.read_at.is_(None))
        total = await self.db.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = await self.db.scalars(
            stmt.order_by(Notification.created_at.desc()).limit(limit).offset(offset)
        )
        return list(rows.all()), int(total or 0)

    async def unread_count(self, user_id: uuid.UUID) -> int:
        return int(
            await self.db.scalar(
                select(func.count())
                .select_from(Notification)
                .where(Notification.user_id == user_id, Notification.read_at.is_(None))
            )
            or 0
        )

    async def mark_read(self, user_id: uuid.UUID, notification_id: uuid.UUID | None = None) -> None:
        stmt = update(Notification).where(Notification.user_id == user_id, Notification.read_at.is_(None))
        if notification_id is not None:
            stmt = stmt.where(Notification.id == notification_id)
        await self.db.execute(stmt.values(read_at=datetime.now(UTC)))
        await self.db.commit()
