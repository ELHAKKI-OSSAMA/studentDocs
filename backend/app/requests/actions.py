"""Every state change of a request goes through this module (state machine + guards + side effects)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.academic.models import DeliveryMode
from app.audit.service import record
from app.auth.dependencies import CurrentUser
from app.auth.permissions import Perm
from app.core.errors import AppError, ConflictError, NotFoundError, PermissionDeniedError
from app.documents.models import Document, DocumentKind
from app.documents.service import PendingUploads
from app.documents.storage import ObjectStorage
from app.documents.validation import ValidatedFile
from app.messages.models import AuthorSide, MessageKind, RequestMessage
from app.notifications.service import NotificationService, NotificationType
from app.requests.models import TERMINAL_STATUSES, Request, RequestStatus
from app.requests.service import UPLOAD_ISSUED_STATUSES, add_history
from app.requests.workflow import Actor, find_transition
from app.users.models import RolePermission, User

MAX_MESSAGE_LENGTH = 5000


class TransitionNotAllowedError(AppError):
    status_code = 409
    code = "transition_not_allowed"


def _clean_body(body: str | None, *, required: bool) -> str | None:
    text = (body or "").replace("\x00", "").strip()
    if len(text) > MAX_MESSAGE_LENGTH:
        raise AppError.of(422, "message_too_long", "Message is too long", {"max_length": MAX_MESSAGE_LENGTH})
    if required and not text:
        raise AppError.of(422, "message_required", "A message is required")
    return text or None


class RequestActions:
    def __init__(self, db: AsyncSession, storage: ObjectStorage | None = None) -> None:
        self.db = db
        self.storage = storage
        self.notifications = NotificationService(db)

    async def _lock(self, request_id: uuid.UUID) -> Request:
        """Row lock: concurrent actions on the same request are serialized."""
        request = await self.db.scalar(
            select(Request)
            .where(Request.id == request_id)
            .with_for_update(of=Request)
            .execution_options(populate_existing=True)
        )
        if request is None:
            raise NotFoundError("Request not found")
        return request

    async def _commit(self) -> None:
        try:
            await self.db.commit()
        except StaleDataError as exc:
            await self.db.rollback()
            raise ConflictError.of(409, "concurrent_update", "The request was modified concurrently") from exc

    async def _guard_delivery(self, request: Request, target: RequestStatus) -> None:
        modes = {item.document_type.delivery_mode for item in request.items}
        issued = await self.db.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.request_id == request.id, Document.kind == DocumentKind.ISSUED)
        )
        has_digital = DeliveryMode.DIGITAL in modes
        has_pickup = DeliveryMode.PICKUP in modes
        if target == RequestStatus.DOCUMENT_AVAILABLE:
            if has_pickup:
                raise AppError.of(
                    422, "delivery_mode_mismatch", "Some documents must be picked up: use READY_FOR_PICKUP"
                )
            if not issued:
                raise AppError.of(422, "issued_document_required", "Upload the final document first")
        if target == RequestStatus.READY_FOR_PICKUP:
            if not has_pickup:
                raise AppError.of(422, "delivery_mode_mismatch", "Digital documents: use DOCUMENT_AVAILABLE")
            if has_digital and not issued:
                raise AppError.of(422, "issued_document_required", "Upload the final document first")

    def _apply(
        self,
        request: Request,
        target: RequestStatus,
        *,
        actor: User,
        actor_role: Actor,
        comment: str | None,
        ip: str | None,
    ) -> None:
        previous = request.status
        request.status = target
        now = datetime.now(UTC)
        if target in (RequestStatus.REJECTED, RequestStatus.CANCELLED):
            request.status_reason = comment
        if target in TERMINAL_STATUSES:
            request.closed_at = now
        add_history(
            self.db, request, previous, target, actor_id=actor.id, actor_role=actor_role, comment=comment
        )
        record(
            self.db,
            actor_id=actor.id,
            action="STATUS_CHANGED",
            entity="request",
            entity_id=request.id,
            ip=ip,
            details={"from": previous.value, "to": target.value},
        )

    def _message(
        self,
        request: Request,
        author: User,
        side: AuthorSide,
        body: str,
        kind: MessageKind = MessageKind.MESSAGE,
    ) -> RequestMessage:
        message = RequestMessage(
            id=uuid.uuid4(),
            request_id=request.id,
            author_user_id=author.id,
            author_side=side,
            kind=kind,
            body=body,
        )
        self.db.add(message)
        return message

    # --- staff ----------------------------------------------------------------------------------------

    async def transition(
        self,
        request_id: uuid.UUID,
        target: RequestStatus,
        comment: str | None,
        current: CurrentUser,
        ip: str | None,
    ) -> Request:
        request = await self._lock(request_id)
        transition = find_transition(request.status, target, Actor.STAFF)
        if transition is None:
            raise TransitionNotAllowedError(
                f"Cannot move a request from {request.status.value} to {target.value}",
                {"from": request.status.value, "to": target.value},
            )
        if transition.permission and not current.has(transition.permission):
            raise PermissionDeniedError("You do not have permission to perform this transition")
        comment = _clean_body(comment, required=transition.requires_comment)
        await self._guard_delivery(request, target)

        self._apply(request, target, actor=current.user, actor_role=Actor.STAFF, comment=comment, ip=ip)
        student_user_id = request.student.user_id
        if target == RequestStatus.NEEDS_INFORMATION:
            self._message(request, current.user, AuthorSide.STAFF, comment, MessageKind.INFORMATION_REQUEST)
            self.notifications.notify(student_user_id, NotificationType.INFORMATION_REQUESTED, request)
        else:
            self.notifications.notify(student_user_id, NotificationType.STATUS_CHANGED, request)
        await self._commit()
        return request

    async def _assignable(self, user_id: uuid.UUID) -> User:
        user = await self.db.get(User, user_id)
        processes = (
            await self.db.scalar(
                select(RolePermission.permission_code).where(
                    RolePermission.role == user.role,
                    RolePermission.permission_code == Perm.REQUESTS_PROCESS.value,
                )
            )
            if user
            else None
        )
        if user is None or not user.is_active or not processes:
            raise AppError.of(422, "invalid_assignee", "This user cannot handle requests")
        return user

    async def assign(
        self, request_id: uuid.UUID, assignee_id: uuid.UUID | None, current: CurrentUser, ip: str | None
    ) -> Request:
        request = await self._lock(request_id)
        if request.status in TERMINAL_STATUSES:
            raise TransitionNotAllowedError("A closed request cannot be reassigned")
        assignee = await self._assignable(assignee_id) if assignee_id else None
        request.assigned_to_id = assignee.id if assignee else None
        record(
            self.db,
            actor_id=current.id,
            action="REQUEST_ASSIGNED",
            entity="request",
            entity_id=request.id,
            ip=ip,
            details={"assignee_id": str(assignee.id) if assignee else None},
        )
        if assignee and assignee.id != current.id:
            self.notifications.notify(assignee.id, NotificationType.REQUEST_ASSIGNED, request)
        await self._commit()
        return request

    async def upload_issued(
        self, request_id: uuid.UUID, files: list[ValidatedFile], current: CurrentUser, ip: str | None
    ) -> list[Document]:
        if not files:
            raise AppError.of(422, "file_required", "Select at least one file")
        request = await self._lock(request_id)
        if request.status not in UPLOAD_ISSUED_STATUSES:
            raise TransitionNotAllowedError("Final documents can be uploaded while PROCESSING or APPROVED")
        uploads = PendingUploads(self.storage)
        try:
            docs = []
            for file in files:
                doc = await uploads.store(
                    self.db, file, request_id=request.id, kind=DocumentKind.ISSUED, uploaded_by=current.id
                )
                await self.db.flush()
                record(
                    self.db,
                    actor_id=current.id,
                    action="DOCUMENT_UPLOADED",
                    entity="document",
                    entity_id=doc.id,
                    ip=ip,
                    details={"request_id": str(request.id), "kind": "ISSUED"},
                )
                docs.append(doc)
            request.updated_at = datetime.now(UTC)
            await self._commit()
        except BaseException:
            await self.db.rollback()
            await uploads.rollback()
            raise
        return docs

    # --- student --------------------------------------------------------------------------------------

    async def cancel_by_student(
        self, request_id: uuid.UUID, student_id: uuid.UUID, current: CurrentUser, ip: str | None
    ) -> Request:
        request = await self._lock(request_id)
        if request.student_id != student_id:
            raise NotFoundError("Request not found")
        if find_transition(request.status, RequestStatus.CANCELLED, Actor.STUDENT) is None:
            raise TransitionNotAllowedError(
                "This request is already being processed and can no longer be cancelled",
                {"from": request.status.value, "to": RequestStatus.CANCELLED.value},
            )
        self._apply(
            request,
            RequestStatus.CANCELLED,
            actor=current.user,
            actor_role=Actor.STUDENT,
            comment=None,
            ip=ip,
        )
        if request.assigned_to_id:
            self.notifications.notify(request.assigned_to_id, NotificationType.STATUS_CHANGED, request)
        await self._commit()
        return request

    # --- messages (both sides) --------------------------------------------------------------------------

    async def post_message(
        self,
        request_id: uuid.UUID,
        body: str | None,
        files: list[ValidatedFile],
        current: CurrentUser,
        *,
        side: AuthorSide,
        student_id: uuid.UUID | None,
        respond: bool,
        ip: str | None,
    ) -> RequestMessage:
        """Posts a message. With `respond`, the student answers an information request (→ IN_REVIEW)."""
        request = await self._lock(request_id)
        if side == AuthorSide.STUDENT and request.student_id != student_id:
            raise NotFoundError("Request not found")
        if request.status in TERMINAL_STATUSES:
            raise TransitionNotAllowedError("This request is closed")
        text = _clean_body(body, required=True)
        if respond and find_transition(request.status, RequestStatus.IN_REVIEW, Actor.STUDENT) is None:
            raise TransitionNotAllowedError("No information was requested for this request")

        kind = MessageKind.INFORMATION_RESPONSE if respond else MessageKind.MESSAGE
        message = self._message(request, current.user, side, text, kind)
        uploads = PendingUploads(self.storage)
        try:
            await self.db.flush()
            for file in files:
                doc = await uploads.store(
                    self.db,
                    file,
                    request_id=request.id,
                    kind=DocumentKind.MESSAGE,
                    uploaded_by=current.id,
                    message_id=message.id,
                )
                await self.db.flush()
                record(
                    self.db,
                    actor_id=current.id,
                    action="DOCUMENT_UPLOADED",
                    entity="document",
                    entity_id=doc.id,
                    ip=ip,
                    details={"request_id": str(request.id), "kind": "MESSAGE"},
                )
            record(
                self.db,
                actor_id=current.id,
                action="MESSAGE_SENT",
                entity="request",
                entity_id=request.id,
                ip=ip,
                details={"message_id": str(message.id), "kind": kind.value},
            )
            if respond:
                self._apply(
                    request,
                    RequestStatus.IN_REVIEW,
                    actor=current.user,
                    actor_role=Actor.STUDENT,
                    comment=None,
                    ip=ip,
                )
            else:
                request.updated_at = datetime.now(UTC)
            if side == AuthorSide.STAFF:
                self.notifications.notify(request.student.user_id, NotificationType.NEW_MESSAGE, request)
            else:
                notification = (
                    NotificationType.INFORMATION_PROVIDED if respond else NotificationType.NEW_MESSAGE
                )
                self.notifications.notify(request.assigned_to_id, notification, request)
            await self._commit()
        except BaseException:
            await self.db.rollback()
            await uploads.rollback()
            raise
        return message

    async def mark_messages_read(self, request_id: uuid.UUID, reader_side: AuthorSide) -> None:
        await self.db.execute(
            update(RequestMessage)
            .where(
                RequestMessage.request_id == request_id,
                RequestMessage.author_side != reader_side,
                RequestMessage.read_at.is_(None),
            )
            .values(read_at=datetime.now(UTC))
        )
        await self.db.commit()
