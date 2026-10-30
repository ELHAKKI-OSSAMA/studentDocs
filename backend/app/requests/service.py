"""Request creation and read models. State changes live in `actions.py`."""

import uuid
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import Select, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.academic.models import AcademicYearStatus, Branch, DocumentType
from app.audit.service import record
from app.auth.dependencies import CurrentUser
from app.auth.permissions import Perm
from app.core.crud import PageParams, paginate
from app.core.errors import AppError, NotFoundError
from app.documents.models import Document, DocumentKind
from app.documents.service import DocumentPipeline, audit_upload, documents_of
from app.documents.upload import ParsedForm
from app.messages.models import AuthorSide, RequestMessage
from app.notifications.service import NotificationService, NotificationType
from app.requests.models import (
    TERMINAL_STATUSES,
    Request,
    RequestItem,
    RequestSequence,
    RequestSource,
    RequestStatus,
    RequestStatusHistory,
)
from app.requests.schemas import (
    DocumentOut,
    HistoryOut,
    ItemOut,
    PersonRef,
    RequestCreate,
    RequestDetail,
    RequestListItem,
    RequestSummary,
    StudentInfo,
)
from app.requests.workflow import Actor, allowed_targets
from app.students.models import EnrollmentStatus, Student, StudentEnrollment
from app.users.models import User

ATTACHMENT_FIELD_PREFIX = "attachment:"
# Issued documents become visible to the student only once the request reaches these statuses.
DOCUMENTS_VISIBLE_TO_STUDENT = frozenset(
    {RequestStatus.DOCUMENT_AVAILABLE, RequestStatus.READY_FOR_PICKUP, RequestStatus.COMPLETED}
)
UPLOAD_ISSUED_STATUSES = frozenset({RequestStatus.PROCESSING, RequestStatus.APPROVED})


def add_history(
    db: AsyncSession,
    request: Request,
    from_status: RequestStatus | None,
    to_status: RequestStatus,
    *,
    actor_id: uuid.UUID | None,
    actor_role: str,
    comment: str | None = None,
) -> None:
    db.add(
        RequestStatusHistory(
            request_id=request.id,
            from_status=from_status,
            to_status=to_status,
            actor_user_id=actor_id,
            actor_role=actor_role,
            comment=comment,
        )
    )


async def next_reference(db: AsyncSession, now: datetime) -> str:
    """Atomic per-year counter (row lock held until commit)."""
    stmt = (
        insert(RequestSequence)
        .values(year=now.year, last_value=1)
        .on_conflict_do_update(
            index_elements=[RequestSequence.year], set_={"last_value": RequestSequence.last_value + 1}
        )
        .returning(RequestSequence.last_value)
    )
    value = await db.scalar(stmt)
    return f"REQ-{now.year}-{value:06d}"


def visible_documents(docs: list[Document], request: Request, *, staff: bool) -> list[Document]:
    if staff or request.status in DOCUMENTS_VISIBLE_TO_STUDENT:
        return docs
    return [d for d in docs if d.kind != DocumentKind.ISSUED]


class RequestService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # --- creation ---------------------------------------------------------------------------------

    async def create(
        self,
        student: Student,
        data: RequestCreate,
        form: ParsedForm,
        documents: DocumentPipeline,
        *,
        ip: str | None,
    ) -> Request:
        """Web submission by the student (multipart form with the supporting documents)."""
        enrollment, types = await self.validate_new_request(student, data)

        # Supporting documents: enforced here, whatever the client does.
        files_by_type: dict[uuid.UUID, list] = defaultdict(list)
        for field_name, file in form.files:
            if not field_name.startswith(ATTACHMENT_FIELD_PREFIX):
                raise AppError.of(422, "unexpected_file", "Unexpected file field", {"field": field_name})
            try:
                type_id = uuid.UUID(field_name.removeprefix(ATTACHMENT_FIELD_PREFIX))
            except ValueError as exc:
                raise AppError.of(
                    422, "unexpected_file", "Unexpected file field", {"field": field_name}
                ) from exc
            if type_id not in types:
                raise AppError.of(422, "unexpected_file", "File for a document that is not requested")
            files_by_type[type_id].append(file)
        self.check_required_attachments(types, {t for t, files in files_by_type.items() if files})

        request = await self.insert_request(
            student,
            enrollment,
            data,
            source=RequestSource.WEB,
            actor_id=student.user_id,
            actor_role=Actor.STUDENT,
        )
        uploads = documents.uploads()
        try:
            item_by_type = {i.document_type_id: i for i in request.items}
            for type_id, files in files_by_type.items():
                for file in files:
                    doc = await uploads.store(
                        self.db,
                        file,
                        request_id=request.id,
                        kind=DocumentKind.ATTACHMENT,
                        uploaded_by=student.user_id,
                        request_item_id=item_by_type[type_id].id,
                    )
                    await self.db.flush()
                    audit_upload(self.db, doc, actor_id=student.user_id, ip=ip)
            self.record_created(request, student, actor_id=student.user_id, ip=ip)
            await self.db.commit()
        except BaseException:
            await self.db.rollback()
            await uploads.rollback()
            raise
        # The supporting documents are received, not accepted: they become usable once scanned CLEAN.
        uploads.dispatch()
        return await self.get(request.id)

    # --- creation core (shared by the web form and the email conversion) ---------------------------

    async def validate_new_request(
        self, student: Student, data: RequestCreate
    ) -> tuple[StudentEnrollment, dict[uuid.UUID, DocumentType]]:
        """Business rules of a new request: verified enrollment of THIS student, active year and branch,
        document types active and allowed for the branch category, quantities within the maximum."""
        enrollment = await self.db.scalar(
            select(StudentEnrollment).where(
                StudentEnrollment.id == data.enrollment_id, StudentEnrollment.student_id == student.id
            )
        )
        if enrollment is None:
            raise AppError.of(422, "invalid_reference", "Unknown enrollment", {"field": "enrollment_id"})
        if enrollment.status != EnrollmentStatus.VERIFIED:
            raise AppError.of(
                422, "enrollment_not_verified", "This enrollment has not been verified by the administration"
            )
        branch: Branch = enrollment.branch
        if enrollment.academic_year.status != AcademicYearStatus.ACTIVE or not branch.is_active:
            raise AppError.of(422, "invalid_reference", "The academic year or branch is no longer active")

        type_ids = [i.document_type_id for i in data.items]
        types = {
            t.id: t
            for t in (await self.db.scalars(select(DocumentType).where(DocumentType.id.in_(type_ids)))).all()
        }
        for item in data.items:
            doc_type = types.get(item.document_type_id)
            allowed_categories = {c.id for c in doc_type.allowed_categories} if doc_type else set()
            if (
                doc_type is None
                or not doc_type.is_active
                or (allowed_categories and branch.category_id not in allowed_categories)
            ):
                raise AppError.of(
                    422,
                    "document_type_not_allowed",
                    "This document cannot be requested for this enrollment",
                    {"document_type_id": str(item.document_type_id)},
                )
            if item.quantity > doc_type.max_quantity:
                raise AppError.of(
                    422,
                    "quantity_exceeded",
                    "Requested quantity exceeds the allowed maximum",
                    {"document_type_id": str(doc_type.id), "max_quantity": doc_type.max_quantity},
                )
        return enrollment, types

    @staticmethod
    def check_required_attachments(types: dict[uuid.UUID, DocumentType], provided: set[uuid.UUID]) -> None:
        missing = [str(t.id) for t in types.values() if t.requires_attachment and t.id not in provided]
        if missing:
            raise AppError.of(
                422,
                "attachment_required",
                "A supporting document is required for some of the requested documents",
                {"document_type_ids": missing},
            )

    async def insert_request(
        self,
        student: Student,
        enrollment: StudentEnrollment,
        data: RequestCreate,
        *,
        source: RequestSource,
        actor_id: uuid.UUID,
        actor_role: str,
    ) -> Request:
        """Inserts the request (SUBMITTED by the actor, then RECEIVED by the system). Not committed."""
        now = datetime.now(UTC)
        request = Request(
            reference=await next_reference(self.db, now),
            student_id=student.id,
            enrollment_id=enrollment.id,
            academic_year_id=enrollment.academic_year_id,
            branch_id=enrollment.branch_id,
            study_level_id=enrollment.study_level_id,
            source=source,
            status=RequestStatus.SUBMITTED,
            reason=data.reason,
            extra_info=data.extra_info,
            submitted_at=now,
        )
        request.items = [
            RequestItem(document_type_id=i.document_type_id, quantity=i.quantity, position=pos)
            for pos, i in enumerate(data.items)
        ]
        self.db.add(request)
        await self.db.flush()
        add_history(self.db, request, None, RequestStatus.SUBMITTED, actor_id=actor_id, actor_role=actor_role)
        # SUBMITTED → RECEIVED is a system transition performed once everything is persisted.
        request.status = RequestStatus.RECEIVED
        add_history(
            self.db,
            request,
            RequestStatus.SUBMITTED,
            RequestStatus.RECEIVED,
            actor_id=None,
            actor_role=Actor.SYSTEM,
        )
        return request

    def record_created(
        self, request: Request, student: Student, *, actor_id: uuid.UUID, ip: str | None, **extra
    ) -> None:
        record(
            self.db,
            actor_id=actor_id,
            action="REQUEST_CREATED",
            entity="request",
            entity_id=request.id,
            ip=ip,
            details={"reference": request.reference, **extra},
        )
        NotificationService(self.db).notify(student.user_id, NotificationType.REQUEST_RECEIVED, request)

    # --- queries ------------------------------------------------------------------------------------

    async def get(self, request_id: uuid.UUID) -> Request:
        request = await self.db.get(Request, request_id, populate_existing=True)
        if request is None:
            raise NotFoundError("Request not found")
        return request

    async def get_for_student(self, request_id: uuid.UUID, student_id: uuid.UUID) -> Request:
        """Another student's request is indistinguishable from a missing one (404)."""
        request = await self.db.get(Request, request_id)
        if request is None or request.student_id != student_id:
            raise NotFoundError("Request not found")
        return request

    def _base(self) -> Select:
        return select(Request).order_by(Request.created_at.desc())

    async def list_for_student(self, student_id: uuid.UUID, status: RequestStatus | None, params: PageParams):
        stmt = self._base().where(Request.student_id == student_id)
        if status:
            stmt = stmt.where(Request.status == status)
        return await paginate(self.db, stmt, params)

    async def list_for_staff(
        self,
        params: PageParams,
        *,
        status: RequestStatus | None,
        q: str | None,
        academic_year_id: uuid.UUID | None,
        branch_id: uuid.UUID | None,
        category_id: uuid.UUID | None,
        assigned: str | None,
        current_user_id: uuid.UUID,
    ):
        stmt = self._base()
        if status:
            stmt = stmt.where(Request.status == status)
        if academic_year_id:
            stmt = stmt.where(Request.academic_year_id == academic_year_id)
        if branch_id:
            stmt = stmt.where(Request.branch_id == branch_id)
        if category_id:
            stmt = stmt.where(
                Request.branch_id.in_(select(Branch.id).where(Branch.category_id == category_id))
            )
        if assigned == "me":
            stmt = stmt.where(Request.assigned_to_id == current_user_id)
        elif assigned == "unassigned":
            stmt = stmt.where(Request.assigned_to_id.is_(None))
        elif assigned:
            try:
                stmt = stmt.where(Request.assigned_to_id == uuid.UUID(assigned))
            except ValueError as exc:
                raise AppError.of(422, "validation_error", "Invalid assigned filter") from exc
        if q:
            like = f"%{q.strip()}%"
            student_match = (
                select(Student.id)
                .join(Student.user)
                .where(
                    or_(
                        User.email.ilike(like),
                        func.concat(User.first_name, " ", User.last_name).ilike(like),
                        Student.student_number.ilike(like),
                    )
                )
            )
            stmt = stmt.where(or_(Request.reference.ilike(like), Request.student_id.in_(student_match)))
        return await paginate(self.db, stmt, params)

    async def summary_for_student(self, student_id: uuid.UUID) -> RequestSummary:
        rows = await self.db.execute(
            select(Request.status, func.count())
            .where(Request.student_id == student_id)
            .group_by(Request.status)
        )
        counts = {status: n for status, n in rows.all()}

        def total(*statuses: RequestStatus) -> int:
            return sum(counts.get(s, 0) for s in statuses)

        S = RequestStatus
        return RequestSummary(
            pending=total(S.SUBMITTED, S.RECEIVED),
            in_progress=total(S.IN_REVIEW, S.PROCESSING, S.APPROVED),
            # The student has something to do: answer, download or pick up.
            action_required=total(S.NEEDS_INFORMATION, S.DOCUMENT_AVAILABLE, S.READY_FOR_PICKUP),
            completed=total(S.COMPLETED),
            closed=total(S.REJECTED, S.CANCELLED),
        )

    async def issued_documents_for_student(self, student_id: uuid.UUID) -> list[tuple[Document, Request]]:
        rows = await self.db.execute(
            select(Document, Request)
            .join(Request, Document.request_id == Request.id)
            .where(
                Request.student_id == student_id,
                Document.kind == DocumentKind.ISSUED,
                Document.deleted_at.is_(None),
                Request.status.in_(DOCUMENTS_VISIBLE_TO_STUDENT),
            )
            .order_by(Document.created_at.desc())
        )
        return [(d, r) for d, r in rows.unique().all()]

    async def unread_counts(
        self, request_ids: list[uuid.UUID], viewer_side: AuthorSide
    ) -> dict[uuid.UUID, int]:
        if not request_ids:
            return {}
        rows = await self.db.execute(
            select(RequestMessage.request_id, func.count())
            .where(
                RequestMessage.request_id.in_(request_ids),
                RequestMessage.author_side != viewer_side,
                RequestMessage.read_at.is_(None),
            )
            .group_by(RequestMessage.request_id)
        )
        return dict(rows.all())

    # --- serialization ------------------------------------------------------------------------------

    @staticmethod
    def _student_info(request: Request) -> StudentInfo:
        user = request.student.user
        return StudentInfo(
            id=request.student.id,
            user_id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
            student_number=request.student.student_number,
        )

    def list_item(self, request: Request, unread: int, *, staff: bool) -> RequestListItem:
        assignee = request.assigned_to
        return RequestListItem(
            id=request.id,
            reference=request.reference,
            status=request.status,
            source=request.source,
            priority=request.priority,
            created_at=request.created_at,
            updated_at=request.updated_at,
            academic_year=request.academic_year,
            branch=request.branch,
            items=[ItemOut.model_validate(i) for i in request.items],
            unread_messages=unread,
            student=self._student_info(request) if staff else None,
            assigned_to=PersonRef(
                id=assignee.id, first_name=assignee.first_name, last_name=assignee.last_name
            )
            if staff and assignee
            else None,
        )

    async def detail(self, request: Request, current: CurrentUser, *, staff: bool) -> RequestDetail:
        side = AuthorSide.STAFF if staff else AuthorSide.STUDENT
        unread = (await self.unread_counts([request.id], side)).get(request.id, 0)
        docs = visible_documents(await documents_of(self.db, request.id), request, staff=staff)
        history = (
            await self.db.scalars(
                select(RequestStatusHistory)
                .where(RequestStatusHistory.request_id == request.id)
                .order_by(RequestStatusHistory.id)
            )
        ).all()
        open_ = request.status not in TERMINAL_STATUSES
        if staff:
            transitions = allowed_targets(request.status, Actor.STAFF, current.permissions)
            can_cancel = can_respond = False
            can_message = open_ and current.has(Perm.REQUESTS_PROCESS)
            can_assign = open_ and current.has(Perm.REQUESTS_ASSIGN)
            can_upload = request.status in UPLOAD_ISSUED_STATUSES and current.has(Perm.REQUESTS_PROCESS)
        else:
            student_targets = allowed_targets(request.status, Actor.STUDENT, current.permissions)
            transitions = []
            can_cancel = RequestStatus.CANCELLED in student_targets
            can_respond = RequestStatus.IN_REVIEW in student_targets
            can_message = open_
            can_assign = can_upload = False
        base = self.list_item(request, unread, staff=staff)
        return RequestDetail(
            **base.model_dump(),
            study_level=request.study_level,
            enrollment_status=request.enrollment.status,
            reason=request.reason,
            extra_info=request.extra_info,
            status_reason=request.status_reason,
            submitted_at=request.submitted_at,
            closed_at=request.closed_at,
            documents=[DocumentOut.of(d, staff=staff) for d in docs],
            history=[HistoryOut.model_validate(h) for h in history],
            available_transitions=transitions,
            can_cancel=can_cancel,
            can_respond=can_respond,
            can_message=can_message,
            can_assign=can_assign,
            can_upload_document=can_upload,
        )
