"""Human review of email cases. Every decision here is taken by an authenticated staff member with the
matching permission, through CSRF-protected endpoints, and is audited. Nothing here is driven by the AI:
its extraction only pre-fills the review screen.

Status rules (strict):
    NEEDS_REVIEW → CONVERTED   convert (creates a NEW request, atomically)
    NEEDS_REVIEW → LINKED      link to an EXISTING open request (message + clean attachments)
    NEEDS_REVIEW | FAILED → DISMISSED (reason) | IGNORED (reason)
    DISMISSED | IGNORED → NEEDS_REVIEW (reopen; NEW if it was never processed)
    FAILED → NEW (retry, except too_large)
    NEEDS_REVIEW → AI_PROCESSING (re-extract, when an AI provider is configured)
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from fastapi.responses import StreamingResponse
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.ai.extraction import assess, latest_extraction
from app.ai.models import AiExtraction
from app.audit.service import record
from app.auth.dependencies import CurrentUser
from app.auth.permissions import Perm
from app.core.crud import PageParams, paginate
from app.core.errors import AppError, ConflictError, NotFoundError
from app.documents.models import Document, ScanStatus
from app.documents.service import DocumentPipeline
from app.documents.storage import ObjectStorage, StorageObjectMissing
from app.emails.models import (
    CLOSED_CASE_STATUSES,
    EmailAccount,
    EmailCase,
    EmailCaseReview,
    EmailCaseStatus,
    EmailMessage,
    IdentificationMethod,
    ReviewConfidence,
    ReviewDecision,
    lock_case,
)
from app.emails.schemas import (
    CandidateOut,
    ConvertIn,
    CorrectionIn,
    EmailCaseDetail,
    EmailCaseListItem,
    EmailStats,
    ExtractionOut,
    LinkIn,
    RejectedAttachment,
    RequestRef,
    ReviewOut,
    StudentRef,
)
from app.messages.models import AuthorSide, MessageKind, RequestMessage
from app.notifications.service import NotificationService, NotificationType
from app.requests.models import TERMINAL_STATUSES, Request, RequestSource, RequestStatus
from app.requests.schemas import DocumentOut, PersonRef, RequestCreate, RequestItemIn
from app.requests.service import RequestService, add_history
from app.requests.workflow import Actor, find_transition
from app.students.models import Student
from app.users.models import Role, User

MAX_LINK_BODY = 5000


@dataclass
class EmailTaskQueue:
    """Hands cases to the worker once the API transaction has committed."""

    send_process: Callable[[str], None]
    send_extract: Callable[[str], None]

    def process(self, case_id: uuid.UUID) -> None:
        self.send_process(str(case_id))

    def extract(self, case_id: uuid.UUID) -> None:
        self.send_extract(str(case_id))


def celery_email_queue(email_queue: str, ai_queue: str) -> EmailTaskQueue:
    from app.worker.tasks import extract_email_task, process_email_task

    return EmailTaskQueue(
        send_process=lambda cid: process_email_task.apply_async(args=[cid], queue=email_queue),
        send_extract=lambda cid: extract_email_task.apply_async(args=[cid], queue=ai_queue),
    )


def _student_ref(student: Student | None) -> StudentRef | None:
    if student is None:
        return None
    u = student.user
    return StudentRef(
        id=student.id,
        user_id=u.id,
        first_name=u.first_name,
        last_name=u.last_name,
        email=u.email,
        student_number=student.student_number,
    )


def _person(user: User | None) -> PersonRef | None:
    return PersonRef(id=user.id, first_name=user.first_name, last_name=user.last_name) if user else None


def _request_ref(request: Request | None) -> RequestRef | None:
    if request is None:
        return None
    return RequestRef(
        id=request.id, reference=request.reference, status=request.status, student_id=request.student_id
    )


class EmailCaseService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        documents: DocumentPipeline | None = None,
        tasks: EmailTaskQueue | None = None,
        ai_enabled: bool = False,
    ) -> None:
        self.db = db
        self.documents = documents
        self.tasks = tasks
        self.ai_enabled = ai_enabled

    # --- helpers --------------------------------------------------------------------------------------

    async def _lock(self, case_id: uuid.UUID, *, version: int | None = None) -> EmailCase:
        case = await lock_case(self.db, case_id)
        if case is None:
            raise NotFoundError("Email case not found")
        if version is not None and case.version != version:
            raise ConflictError.of(409, "concurrent_update", "The email case was modified concurrently")
        return case

    @staticmethod
    def _require(case: EmailCase, *statuses: EmailCaseStatus) -> None:
        if case.status not in statuses:
            raise AppError.of(
                409,
                "email_case_status_conflict",
                "This action is not possible in the current status of the email case",
                {"status": case.status.value},
            )

    def _review(
        self, case: EmailCase, current: CurrentUser, decision: ReviewDecision, *, comment=None, corrected=None
    ):
        self.db.add(
            EmailCaseReview(
                email_case_id=case.id,
                actor_id=current.id,
                decision=decision,
                comment=comment,
                corrected_output=corrected,
            )
        )

    def _audit(self, case: EmailCase, current: CurrentUser, action: str, ip: str | None, **details) -> None:
        record(
            self.db,
            actor_id=current.id,
            action=action,
            entity="email_case",
            entity_id=case.id,
            ip=ip,
            details=details,
        )

    async def _commit(self) -> None:
        try:
            await self.db.commit()
        except StaleDataError as exc:
            await self.db.rollback()
            raise ConflictError.of(
                409, "concurrent_update", "The email case was modified concurrently"
            ) from exc

    async def get(self, case_id: uuid.UUID) -> EmailCase:
        case = await self.db.get(EmailCase, case_id, populate_existing=True)
        if case is None:
            raise NotFoundError("Email case not found")
        return case

    async def _attachments(self, case_id: uuid.UUID) -> list[Document]:
        rows = await self.db.scalars(
            select(Document)
            .where(Document.email_case_id == case_id, Document.deleted_at.is_(None))
            .order_by(Document.created_at)
        )
        return list(rows.all())

    async def _refresh_confidence(self, case: EmailCase) -> None:
        extraction = await latest_extraction(self.db, case.id)
        output = extraction.output if extraction is not None else None
        violations = extraction.rule_violations if extraction is not None else []
        assessment = await assess(self.db, case, output, violations)
        case.review_confidence = assessment.level
        case.flags = dict(case.flags or {}) | {
            "review_reasons": assessment.reasons,
            "review_score": assessment.score,
        }

    # --- queries --------------------------------------------------------------------------------------

    def _base(self) -> Select:
        return select(EmailCase).join(EmailMessage, EmailCase.email_message_id == EmailMessage.id)

    async def search(
        self,
        params: PageParams,
        *,
        status: EmailCaseStatus | None,
        confidence: ReviewConfidence | None,
        q: str | None,
        assigned: str | None,
        current_user_id: uuid.UUID,
    ):
        stmt = self._base().order_by(EmailMessage.received_at.desc())
        if status:
            stmt = stmt.where(EmailCase.status == status)
        if confidence:
            stmt = stmt.where(EmailCase.review_confidence == confidence)
        if assigned == "me":
            stmt = stmt.where(EmailCase.assigned_to_id == current_user_id)
        elif assigned == "unassigned":
            stmt = stmt.where(EmailCase.assigned_to_id.is_(None))
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where(
                or_(
                    EmailMessage.from_address.ilike(like),
                    EmailMessage.from_name.ilike(like),
                    EmailMessage.subject.ilike(like),
                    EmailCase.detected_reference.ilike(like),
                )
            )
        return await paginate(self.db, stmt, params)

    async def list_items(self, cases: list[EmailCase]) -> list[EmailCaseListItem]:
        ids = [c.id for c in cases]
        counts: dict[uuid.UUID, tuple[int, bool]] = {}
        if ids:
            rows = await self.db.execute(
                select(
                    Document.email_case_id,
                    func.count(),
                    func.bool_or(Document.scan_status == ScanStatus.INFECTED),
                )
                .where(Document.email_case_id.in_(ids), Document.deleted_at.is_(None))
                .group_by(Document.email_case_id)
            )
            counts = {cid: (n, bool(infected)) for cid, n, infected in rows.all()}
        return [self._item(c, *counts.get(c.id, (0, False))) for c in cases]

    def _item(self, case: EmailCase, attachment_count: int, infected: bool) -> EmailCaseListItem:
        flags = case.flags or {}
        m = case.message
        return EmailCaseListItem(
            id=case.id,
            status=case.status,
            from_address=m.from_address,
            from_name=m.from_name,
            subject=m.subject,
            received_at=m.received_at,
            review_confidence=case.review_confidence,
            student=_student_ref(case.student),
            candidate_count=len(case.candidate_students or []),
            detected_reference=case.detected_reference,
            attachment_count=attachment_count,
            assigned_to=_person(case.assigned_to),
            authentication=flags.get("authentication") or (m.auth_results or {}).get("verdict", "ABSENT"),
            injection_suspected=bool(
                flags.get("injection_suspected") or flags.get("ai_reported_suspicious_content")
            ),
            ai_failed=bool(flags.get("ai_failed")),
            infected_attachment=infected,
            created_at=case.created_at,
        )

    async def detail(self, case: EmailCase, current: CurrentUser) -> EmailCaseDetail:
        docs = await self._attachments(case.id)
        infected = any(d.scan_status == ScanStatus.INFECTED for d in docs)
        base = self._item(case, len(docs), infected)

        candidate_ids = [uuid.UUID(c["student_id"]) for c in case.candidate_students or []]
        students = {}
        if candidate_ids:
            rows = await self.db.scalars(select(Student).where(Student.id.in_(candidate_ids)))
            students = {s.id: s for s in rows.all()}
        candidates = [
            CandidateOut(
                student=_student_ref(students[uuid.UUID(c["student_id"])]),
                reasons=c.get("reasons", []),
                score=c.get("score", 0),
                evidence=c.get("evidence", {}),
            )
            for c in case.candidate_students or []
            if uuid.UUID(c["student_id"]) in students
        ]
        extraction = await latest_extraction(self.db, case.id)
        reviews = (
            await self.db.scalars(
                select(EmailCaseReview)
                .where(EmailCaseReview.email_case_id == case.id)
                .order_by(EmailCaseReview.created_at)
            )
        ).all()
        correction = next(
            (r.corrected_output for r in reversed(reviews) if r.decision == ReviewDecision.CORRECT), None
        )
        linked = await self.db.get(Request, case.linked_request_id) if case.linked_request_id else None
        referenced = (
            await self.db.scalar(select(Request).where(Request.reference == case.detected_reference))
            if case.detected_reference
            else None
        )
        open_ = case.status == EmailCaseStatus.NEEDS_REVIEW
        flags = dict(case.flags or {})
        rejected = [RejectedAttachment(**r) for r in flags.pop("rejected_attachments", [])]
        return EmailCaseDetail(
            **base.model_dump(),
            to_addresses=case.message.to_addresses or [],
            cc_addresses=case.message.cc_addresses or [],
            sent_at=case.message.sent_at,
            message_id_header=case.message.message_id_header,
            identification_method=case.identification_method,
            candidates=candidates,
            body_text=case.body_text,
            body_html=case.body_html_sanitized,
            flags=flags,
            linked_request=_request_ref(linked),
            reference_request=_request_ref(referenced),
            extraction=ExtractionOut.model_validate(extraction, from_attributes=True) if extraction else None,
            correction=correction,
            reviews=[
                ReviewOut(
                    id=r.id,
                    decision=r.decision,
                    actor=_person(r.actor),
                    corrected_output=r.corrected_output,
                    comment=r.comment,
                    created_at=r.created_at,
                )
                for r in reviews
            ],
            documents=[DocumentOut.of(d, staff=True) for d in docs],
            rejected_attachments=rejected,
            failure_code=case.failure_code,
            dismiss_reason=case.dismiss_reason,
            version=case.version,
            can_process=open_ and current.has(Perm.EMAILS_PROCESS),
            can_convert=open_ and current.has(Perm.EMAILS_CONVERT) and current.has(Perm.REQUESTS_PROCESS),
            can_dismiss=case.status in (EmailCaseStatus.NEEDS_REVIEW, EmailCaseStatus.FAILED)
            and current.has(Perm.EMAILS_DISMISS),
            can_read_raw=current.has(Perm.EMAILS_READ_RAW),
            can_reextract=open_ and self.ai_enabled and current.has(Perm.EMAILS_PROCESS),
            can_retry=case.status == EmailCaseStatus.FAILED
            and case.failure_code != "too_large"
            and current.has(Perm.EMAILS_PROCESS),
            can_reopen=case.status in (EmailCaseStatus.DISMISSED, EmailCaseStatus.IGNORED)
            and current.has(Perm.EMAILS_DISMISS),
        )

    # --- staff actions --------------------------------------------------------------------------------

    async def assign(
        self, case_id: uuid.UUID, assignee_id: uuid.UUID | None, current: CurrentUser, ip
    ) -> EmailCase:
        case = await self._lock(case_id)
        if case.status in CLOSED_CASE_STATUSES:
            self._require(case, EmailCaseStatus.NEEDS_REVIEW, EmailCaseStatus.FAILED)
        if assignee_id is not None:
            user = await self.db.get(User, assignee_id)
            if user is None or not user.is_active or user.role == Role.STUDENT:
                raise AppError.of(422, "invalid_assignee", "This user cannot handle email cases")
        case.assigned_to_id = assignee_id
        self._review(case, current, ReviewDecision.ASSIGN, comment=str(assignee_id) if assignee_id else None)
        self._audit(
            case, current, "EMAIL_CASE_ASSIGNED", ip, assignee_id=str(assignee_id) if assignee_id else None
        )
        await self._commit()
        return await self.get(case_id)

    async def associate_student(self, case_id, student_id, comment, current: CurrentUser, ip) -> EmailCase:
        case = await self._lock(case_id)
        self._require(case, EmailCaseStatus.NEEDS_REVIEW)
        student = await self.db.get(Student, student_id)
        if student is None or not student.user.is_active:
            raise AppError.of(422, "invalid_student", "Unknown or inactive student")
        case.student_id = student.id
        case.identification_method = IdentificationMethod.ADMIN_MANUAL
        await self._refresh_confidence(case)
        self._review(
            case,
            current,
            ReviewDecision.ASSOCIATE_STUDENT,
            comment=comment,
            corrected={"student_id": str(student.id)},
        )
        self._audit(case, current, "EMAIL_STUDENT_ASSOCIATED", ip, student_id=str(student.id))
        await self._commit()
        return await self.get(case_id)

    async def correct(self, case_id, data: CorrectionIn, current: CurrentUser, ip) -> EmailCase:
        case = await self._lock(case_id)
        self._require(case, EmailCaseStatus.NEEDS_REVIEW)
        corrected = data.model_dump(mode="json", exclude={"comment"})
        previous = await self.db.scalar(
            select(EmailCaseReview.corrected_output)
            .where(
                EmailCaseReview.email_case_id == case.id, EmailCaseReview.decision == ReviewDecision.CORRECT
            )
            .order_by(EmailCaseReview.created_at.desc())
            .limit(1)
        )
        changed = sorted(k for k, v in corrected.items() if (previous or {}).get(k) != v)
        self._review(case, current, ReviewDecision.CORRECT, comment=data.comment, corrected=corrected)
        # Field names only: the values stay in email_case_reviews.
        self._audit(case, current, "EMAIL_EXTRACTION_CORRECTED", ip, fields=changed)
        case.updated_at = datetime.now(UTC)
        await self._commit()
        return await self.get(case_id)

    async def convert(self, case_id: uuid.UUID, data: ConvertIn, current: CurrentUser, ip) -> Request:
        """One transaction: request + items + history + clean attachments + case CONVERTED + audit +
        notification. Any failure rolls everything back: no partial request, the case is unchanged."""
        try:
            case = await self._lock(case_id, version=data.version)
            self._require(case, EmailCaseStatus.NEEDS_REVIEW)
            student = await self.db.get(Student, data.student_id)
            if student is None or not student.user.is_active or student.user.role != Role.STUDENT:
                raise AppError.of(422, "invalid_student", "Unknown or inactive student")
            if case.student_id is not None and case.student_id != student.id:
                raise AppError.of(
                    422, "student_mismatch", "Associate the email with this student before converting it"
                )
            requests = RequestService(self.db)
            create = RequestCreate(
                enrollment_id=data.enrollment_id,
                items=[
                    RequestItemIn(document_type_id=i.document_type_id, quantity=i.quantity)
                    for i in data.items
                ],
                reason=data.reason,
                extra_info=data.extra_info,
            )
            enrollment, types = await requests.validate_new_request(student, create)

            attachments = {d.id: d for d in await self._attachments(case.id)}
            by_type: dict[uuid.UUID, list[Document]] = {}
            for item in data.items:
                for attachment_id in item.attachment_ids:
                    doc = attachments.get(attachment_id)
                    if doc is None or doc.request_id is not None:
                        raise AppError.of(
                            422,
                            "invalid_attachment",
                            "Unknown attachment",
                            {"attachment_id": str(attachment_id)},
                        )
                    if doc.scan_status != ScanStatus.CLEAN:
                        # INFECTED, ERROR or still SCANNING: never part of a request.
                        raise AppError.of(
                            422,
                            "attachment_not_clean",
                            "Only attachments accepted by the antivirus can be added to a request",
                            {"attachment_id": str(attachment_id), "scan_status": doc.scan_status.value},
                        )
                    by_type.setdefault(item.document_type_id, []).append(doc)
            requests.check_required_attachments(types, set(by_type))

            request = await requests.insert_request(
                student,
                enrollment,
                create,
                source=RequestSource.EMAIL,
                actor_id=current.id,
                actor_role=Actor.STAFF,
            )
            item_by_type = {i.document_type_id: i for i in request.items}
            for type_id, docs in by_type.items():
                for doc in docs:
                    # Same row: the attachment now belongs to the request too (email_case_id is kept).
                    doc.request_id = request.id
                    doc.request_item_id = item_by_type[type_id].id
                    record(
                        self.db,
                        actor_id=current.id,
                        action="DOCUMENT_ATTACHED_FROM_EMAIL",
                        entity="document",
                        entity_id=doc.id,
                        ip=ip,
                        details=doc.owner_details(),
                    )
            case.student_id = student.id
            if case.identification_method is None:
                case.identification_method = IdentificationMethod.ADMIN_MANUAL
            case.status = EmailCaseStatus.CONVERTED
            case.linked_request_id = request.id
            case.reviewed_by_id, case.reviewed_at = current.id, datetime.now(UTC)
            self._review(case, current, ReviewDecision.CONVERT, corrected=data.model_dump(mode="json"))
            self._audit(
                case,
                current,
                "EMAIL_CASE_CONVERTED",
                ip,
                request_id=str(request.id),
                reference=request.reference,
            )
            requests.record_created(
                request, student, actor_id=current.id, ip=ip, source="EMAIL", email_case_id=str(case.id)
            )
            await self._commit()
        except BaseException:
            await self.db.rollback()
            raise
        return await RequestService(self.db).get(request.id)

    async def link(self, case_id: uuid.UUID, data: LinkIn, current: CurrentUser, ip) -> Request:
        """Attaches the email to an existing open request: a student message (the email text) with the
        selected clean attachments; optionally as the answer to an information request."""
        try:
            case = await self._lock(case_id, version=data.version)
            self._require(case, EmailCaseStatus.NEEDS_REVIEW)
            request = await self.db.scalar(
                select(Request).where(Request.id == data.request_id).with_for_update(of=Request)
            )
            if request is None:
                raise AppError.of(422, "invalid_reference", "Unknown request", {"field": "request_id"})
            if request.status in TERMINAL_STATUSES:
                raise AppError.of(409, "request_closed", "This request is closed")
            if case.student_id is None or case.student_id != request.student_id:
                # The message is posted in the student's name: the sender must be that student.
                raise AppError.of(
                    422, "student_mismatch", "Associate the email with the student of this request first"
                )
            if (
                data.as_information_response
                and find_transition(request.status, RequestStatus.IN_REVIEW, Actor.STUDENT) is None
            ):
                raise AppError.of(
                    409, "no_information_requested", "No information was requested for this request"
                )
            attachments = {d.id: d for d in await self._attachments(case.id)}
            docs = []
            for attachment_id in data.attachment_ids:
                doc = attachments.get(attachment_id)
                if doc is None or doc.request_id is not None:
                    raise AppError.of(
                        422, "invalid_attachment", "Unknown attachment", {"attachment_id": str(attachment_id)}
                    )
                if doc.scan_status != ScanStatus.CLEAN:
                    raise AppError.of(
                        422,
                        "attachment_not_clean",
                        "Only attachments accepted by the antivirus can be added to a request",
                        {"attachment_id": str(attachment_id), "scan_status": doc.scan_status.value},
                    )
                docs.append(doc)

            student = await self.db.get(Student, case.student_id)
            subject = case.message.subject
            text = (case.body_text or "").strip()
            body = f"[Email] {subject}\n\n{text}".strip()[:MAX_LINK_BODY]
            kind = MessageKind.INFORMATION_RESPONSE if data.as_information_response else MessageKind.MESSAGE
            message = RequestMessage(
                id=uuid.uuid4(),
                request_id=request.id,
                author_user_id=student.user_id,
                author_side=AuthorSide.STUDENT,
                kind=kind,
                body=body,
            )
            self.db.add(message)
            await self.db.flush()
            for doc in docs:
                doc.request_id = request.id
                doc.message_id = message.id
                record(
                    self.db,
                    actor_id=current.id,
                    action="DOCUMENT_ATTACHED_FROM_EMAIL",
                    entity="document",
                    entity_id=doc.id,
                    ip=ip,
                    details=doc.owner_details(),
                )
            if data.as_information_response:
                previous = request.status
                request.status = RequestStatus.IN_REVIEW
                add_history(
                    self.db,
                    request,
                    previous,
                    RequestStatus.IN_REVIEW,
                    actor_id=current.id,
                    actor_role=Actor.STAFF,
                    comment="email",
                )
                record(
                    self.db,
                    actor_id=current.id,
                    action="STATUS_CHANGED",
                    entity="request",
                    entity_id=request.id,
                    ip=ip,
                    details={"from": previous.value, "to": RequestStatus.IN_REVIEW.value, "source": "email"},
                )
                NotificationService(self.db).notify(
                    request.assigned_to_id, NotificationType.INFORMATION_PROVIDED, request
                )
            else:
                request.updated_at = datetime.now(UTC)
                NotificationService(self.db).notify(
                    request.assigned_to_id, NotificationType.NEW_MESSAGE, request
                )
            case.status = EmailCaseStatus.LINKED
            case.linked_request_id = request.id
            case.reviewed_by_id, case.reviewed_at = current.id, datetime.now(UTC)
            self._review(case, current, ReviewDecision.LINK, corrected={"request_id": str(request.id)})
            self._audit(
                case,
                current,
                "EMAIL_CASE_LINKED",
                ip,
                request_id=str(request.id),
                message_id=str(message.id),
                attachments=len(docs),
            )
            record(
                self.db,
                actor_id=current.id,
                action="MESSAGE_SENT",
                entity="request",
                entity_id=request.id,
                ip=ip,
                details={"message_id": str(message.id), "kind": kind.value, "source": "email"},
            )
            await self._commit()
        except BaseException:
            await self.db.rollback()
            raise
        return await RequestService(self.db).get(request.id)

    async def dismiss(
        self, case_id, reason: str, current: CurrentUser, ip, *, ignore: bool = False
    ) -> EmailCase:
        case = await self._lock(case_id)
        self._require(case, EmailCaseStatus.NEEDS_REVIEW, EmailCaseStatus.FAILED)
        if not reason:
            raise AppError.of(422, "reason_required", "A reason is required")
        case.dismiss_reason = reason[:500]
        case.reviewed_by_id, case.reviewed_at = current.id, datetime.now(UTC)
        if ignore:
            case.status = EmailCaseStatus.IGNORED
            case.flags = dict(case.flags or {}) | {"ignored_rule": "manual"}
            self._review(case, current, ReviewDecision.IGNORE, comment=reason)
            self._audit(case, current, "EMAIL_IGNORED", ip, rule="manual")
        else:
            case.status = EmailCaseStatus.DISMISSED
            self._review(case, current, ReviewDecision.DISMISS, comment=reason)
            # The reason itself stays on the case (it may quote personal data).
            self._audit(case, current, "EMAIL_CASE_DISMISSED", ip, reason_given=True)
        await self._commit()
        return await self.get(case_id)

    async def reopen(self, case_id, comment, current: CurrentUser, ip) -> EmailCase:
        case = await self._lock(case_id)
        self._require(case, EmailCaseStatus.DISMISSED, EmailCaseStatus.IGNORED)
        previous = case.status
        processed = case.body_text is not None
        case.status = EmailCaseStatus.NEEDS_REVIEW if processed else EmailCaseStatus.NEW
        case.dismiss_reason = None
        case.reviewed_by_id = case.reviewed_at = None
        if case.status == EmailCaseStatus.NEEDS_REVIEW:
            await self._refresh_confidence(case)
        self._review(case, current, ReviewDecision.REOPEN, comment=comment)
        self._audit(case, current, "EMAIL_CASE_REOPENED", ip, previous=previous.value, processed=processed)
        await self._commit()
        if case.status == EmailCaseStatus.NEW and self.tasks:
            self.tasks.process(case.id)
        return await self.get(case_id)

    async def retry(self, case_id, current: CurrentUser, ip) -> EmailCase:
        case = await self._lock(case_id)
        self._require(case, EmailCaseStatus.FAILED)
        if case.failure_code == "too_large":
            raise AppError.of(409, "retry_not_possible", "This message is too large to be processed")
        previous = case.failure_code
        case.status, case.failure_code = EmailCaseStatus.NEW, None
        self._review(case, current, ReviewDecision.RETRY)
        self._audit(case, current, "EMAIL_CASE_RETRY", ip, previous_failure=previous)
        await self._commit()
        if self.tasks:
            self.tasks.process(case.id)
        return await self.get(case_id)

    async def reextract(self, case_id, current: CurrentUser, ip) -> EmailCase:
        if not self.ai_enabled:
            raise AppError.of(409, "ai_disabled", "No AI provider is configured")
        case = await self._lock(case_id)
        self._require(case, EmailCaseStatus.NEEDS_REVIEW)
        case.status = EmailCaseStatus.AI_PROCESSING
        self._review(case, current, ReviewDecision.REEXTRACT)
        self._audit(case, current, "AI_EXTRACTION_REQUESTED", ip)
        await self._commit()
        if self.tasks:
            self.tasks.extract(case.id)
        return await self.get(case_id)

    async def rescan_attachment(self, case_id, document_id, current: CurrentUser, ip) -> Document:
        await self._lock(case_id)
        doc = await self.attachment(case_id, document_id)
        if doc.scan_status != ScanStatus.ERROR:
            raise AppError.of(409, "rescan_not_allowed", "Only a document whose scan failed can be rescanned")
        doc.scan_status, doc.scan_detail = ScanStatus.SCANNING, None
        record(
            self.db,
            actor_id=current.id,
            action="DOCUMENT_RESCAN_REQUESTED",
            entity="document",
            entity_id=doc.id,
            ip=ip,
            details=doc.owner_details(),
        )
        await self._commit()
        if self.documents is not None and self.documents.queue is not None:
            self.documents.queue.enqueue([doc.id])
        return doc

    async def attachment(self, case_id: uuid.UUID, document_id: uuid.UUID) -> Document:
        doc = await self.db.scalar(
            select(Document).where(
                Document.id == document_id, Document.email_case_id == case_id, Document.deleted_at.is_(None)
            )
        )
        if doc is None:
            raise NotFoundError("Document not found")
        return doc

    async def raw_download(
        self, case_id: uuid.UUID, storage: ObjectStorage, current: CurrentUser, ip
    ) -> StreamingResponse:
        case = await self.get(case_id)
        message = case.message
        try:
            chunks = await storage.open(message.raw_storage_key)
        except StorageObjectMissing as exc:
            raise NotFoundError("Raw message not found") from exc
        self._audit(case, current, "EMAIL_RAW_DOWNLOADED", ip, sha256=message.raw_sha256)
        await self.db.commit()
        name = f"email-{case.id}.eml"
        return StreamingResponse(
            chunks,
            media_type="message/rfc822",
            headers={
                "Content-Disposition": f"attachment; filename=\"{name}\"; filename*=UTF-8''{quote(name)}",
                "Content-Length": str(message.raw_size_bytes),
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'none'; sandbox",
            },
        )

    async def stats(self, *, ai_provider: str, ai_is_local: bool | None) -> EmailStats:
        by_status = dict(
            (await self.db.execute(select(EmailCase.status, func.count()).group_by(EmailCase.status))).all()
        )
        by_conf = dict(
            (
                await self.db.execute(
                    select(EmailCase.review_confidence, func.count())
                    .where(
                        EmailCase.status == EmailCaseStatus.NEEDS_REVIEW,
                        EmailCase.review_confidence.is_not(None),
                    )
                    .group_by(EmailCase.review_confidence)
                )
            ).all()
        )
        oldest = await self.db.scalar(
            select(func.min(EmailMessage.received_at))
            .join(EmailCase, EmailCase.email_message_id == EmailMessage.id)
            .where(EmailCase.status == EmailCaseStatus.NEEDS_REVIEW)
        )
        since = datetime.now(UTC) - timedelta(hours=24)
        received = await self.db.scalar(
            select(func.count()).select_from(EmailMessage).where(EmailMessage.created_at >= since)
        )
        ai_failed = await self.db.scalar(
            select(func.count())
            .select_from(AiExtraction)
            .where(AiExtraction.error_code.is_not(None), AiExtraction.created_at >= since)
        )
        infected = await self.db.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.email_case_id.is_not(None), Document.scan_status == ScanStatus.INFECTED)
        )
        account = await self.db.scalar(select(EmailAccount).order_by(EmailAccount.created_at).limit(1))
        return EmailStats(
            by_status={k.value: v for k, v in by_status.items()},
            by_confidence={k.value: v for k, v in by_conf.items()},
            awaiting_review=by_status.get(EmailCaseStatus.NEEDS_REVIEW, 0),
            oldest_awaiting_review_at=oldest,
            received_last_24h=int(received or 0),
            ai_failed=int(ai_failed or 0),
            infected_attachments=int(infected or 0),
            mailbox_last_polled_at=account.last_polled_at if account else None,
            mailbox_last_success_at=account.last_success_at if account else None,
            mailbox_last_error=account.last_error if account else None,
            ai_provider=ai_provider,
            ai_is_local=ai_is_local,
        )


async def cases_to_resume(
    db: AsyncSession, *, stale_after: timedelta
) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    """Safety net for lost task messages: NEW cases older than 2 minutes, AI_PROCESSING cases without
    pending scan for 2 minutes, or stuck for longer than `stale_after`."""
    now = datetime.now(UTC)
    new = (
        await db.scalars(
            select(EmailCase.id).where(
                EmailCase.status == EmailCaseStatus.NEW, EmailCase.updated_at < now - timedelta(minutes=2)
            )
        )
    ).all()
    scanning = select(Document.email_case_id).where(
        Document.email_case_id.is_not(None), Document.scan_status == ScanStatus.SCANNING
    )
    processing = (
        await db.scalars(
            select(EmailCase.id).where(
                EmailCase.status == EmailCaseStatus.AI_PROCESSING,
                or_(
                    EmailCase.updated_at < now - stale_after,
                    (EmailCase.updated_at < now - timedelta(minutes=2)) & EmailCase.id.not_in(scanning),
                ),
            )
        )
    ).all()
    return list(new), list(processing)
