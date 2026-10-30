"""NEW case → parse, sanitize, attachments (Phase 3 pipeline), identification, reference → AI_PROCESSING.

Idempotent: the case row is locked (`FOR UPDATE SKIP LOCKED`) and only a NEW case is processed. Every
failure before the commit rolls back the whole step (and removes the attachments written to storage),
so a retry starts from a clean NEW case.
"""

import enum
import io
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.injection import detect as detect_injection
from app.audit.service import record
from app.core.config import Settings
from app.core.errors import AppError
from app.documents.models import DocumentKind
from app.documents.service import DocumentPipeline, audit_upload
from app.documents.storage import ObjectStorage, StorageObjectMissing
from app.documents.validation import original_name, validate_stream
from app.emails.identification import identify
from app.emails.models import EmailAccount, EmailCase, EmailCaseStatus, EmailMessage, lock_case
from app.emails.parsing import EmailParseError, ParsedEmail, parse_message
from app.emails.references import find_reference, normalize_subject, own_text
from app.requests.models import Request

logger = logging.getLogger(__name__)


class ProcessOutcome(enum.StrEnum):
    READY = "READY"  # now AI_PROCESSING: the extraction step follows
    IGNORED = "IGNORED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"  # not NEW anymore, unknown, or locked by another worker


def ignore_rule(parsed: ParsedEmail, own_addresses: set[str]) -> str | None:
    """Deterministic rules applied before any AI. Never decided by a model."""
    if parsed.is_bounce:
        return "bounce"
    if parsed.auto_submitted:
        return "auto_reply"
    if parsed.from_address in own_addresses:
        return "own_address"  # our own message coming back (loop)
    return None


class EmailProcessor:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        storage: ObjectStorage,
        pipeline: DocumentPipeline,
        settings: Settings,
    ) -> None:
        self.sessionmaker = sessionmaker
        self.storage = storage
        self.pipeline = pipeline
        self.settings = settings

    async def process(self, case_id: uuid.UUID) -> ProcessOutcome:
        async with self.sessionmaker() as db:
            case = await lock_case(db, case_id, skip_locked=True)
            if case is None or case.status != EmailCaseStatus.NEW:
                return ProcessOutcome.SKIPPED
            message: EmailMessage = case.message
            account = await db.get(EmailAccount, message.account_id)
            case.attempts += 1
            try:
                raw = await self.storage.get(message.raw_storage_key)
            except StorageObjectMissing:
                return await self._fail(db, case, "raw_missing")
            try:
                parsed = parse_message(
                    raw,
                    body_max_chars=self.settings.email_body_max_chars,
                    html_max_bytes=self.settings.email_html_max_bytes,
                )
            except EmailParseError:
                return await self._fail(db, case, "parse_error")

            normalized, is_reply, is_forward = normalize_subject(parsed.subject)
            flags = dict(case.flags or {}) | parsed.flags
            flags |= {"is_reply": is_reply, "is_forward": is_forward, "normalized_subject": normalized[:300]}
            flags["authentication"] = (message.auth_results or {}).get("verdict", "ABSENT")
            case.body_text = parsed.body_text
            case.body_html_sanitized = parsed.body_html

            own = {account.address.lower(), self._mail_from_address()}
            if rule := ignore_rule(parsed, own):
                case.flags = flags | {"ignored_rule": rule}
                case.status = EmailCaseStatus.IGNORED
                record(
                    db,
                    actor_id=None,
                    action="EMAIL_IGNORED",
                    entity="email_case",
                    entity_id=case.id,
                    details={"rule": rule},
                )
                await db.commit()
                return ProcessOutcome.IGNORED

            reference = find_reference(parsed.subject, parsed.body_text)
            reference_request = None
            if reference:
                reference_request = await db.scalar(select(Request).where(Request.reference == reference))
                if reference_request is None:
                    flags["unknown_reference"] = reference
                else:
                    case.detected_reference = reference
                    if reference_request.student.user.email.lower() != parsed.from_address:
                        # Someone else quotes the reference: shown as a warning to the reviewer.
                        flags["reference_sender_mismatch"] = True

            sender_text = own_text(parsed.body_text)
            injection = detect_injection(f"{parsed.subject}\n{parsed.body_text}")
            if injection:
                flags["injection_suspected"] = injection

            ident = await identify(
                db,
                from_address=parsed.from_address,
                from_name=parsed.from_name,
                auth_verdict=flags["authentication"],
                own_text=f"{parsed.subject}\n{sender_text}",
                reference_request=reference_request,
            )
            case.student_id = ident.student_id
            case.identification_method = ident.method
            case.candidate_students = ident.candidates

            uploads = self.pipeline.uploads()
            try:
                await self._store_attachments(db, case, parsed, flags, uploads)
                case.flags = flags
                case.status = EmailCaseStatus.AI_PROCESSING
                record(
                    db,
                    actor_id=None,
                    action="EMAIL_PROCESSED",
                    entity="email_case",
                    entity_id=case.id,
                    details={
                        "attachments": len(uploads.documents),
                        "rejected_attachments": len(flags.get("rejected_attachments", [])),
                        "student_identified": ident.student_id is not None,
                        "candidates": len(ident.candidates),
                        "reference": bool(case.detected_reference),
                        "injection_suspected": bool(injection),
                    },
                )
                if ident.candidates:
                    record(
                        db,
                        actor_id=None,
                        action="EMAIL_STUDENT_PROPOSED",
                        entity="email_case",
                        entity_id=case.id,
                        details={
                            "candidates": len(ident.candidates),
                            "method": ident.method.value if ident.method else None,
                        },
                    )
                await db.commit()
            except BaseException:
                await db.rollback()
                await uploads.rollback()
                raise
        uploads.dispatch()  # antivirus scans, once the rows exist
        return ProcessOutcome.READY

    async def _store_attachments(
        self, db, case: EmailCase, parsed: ParsedEmail, flags: dict, uploads
    ) -> None:
        limit = self.settings.email_max_attachments
        rejected = []
        stored = 0
        for attachment in parsed.attachments:
            name = original_name(attachment.filename) or "attachment"
            if stored >= limit:
                flags["attachments_truncated"] = True
                rejected.append(
                    {"filename": name, "code": "too_many_attachments", "size_bytes": len(attachment.data)}
                )
                continue
            try:
                file = validate_stream(
                    name,
                    io.BytesIO(attachment.data),
                    self.settings.max_upload_bytes,
                    attachment.declared_type,
                )
            except AppError as exc:
                # Not stored as a document (never downloadable); it stays inside the raw .eml only.
                rejected.append({"filename": name, "code": exc.code, "size_bytes": len(attachment.data)})
                continue
            doc = await uploads.store(
                db,
                file,
                request_id=None,
                email_case_id=case.id,
                kind=DocumentKind.EMAIL_ATTACHMENT,
                uploaded_by=None,
            )
            await db.flush()
            audit_upload(db, doc, actor_id=None, ip=None)
            stored += 1
        if rejected:
            flags["rejected_attachments"] = rejected[:50]

    async def _fail(self, db: AsyncSession, case: EmailCase, code: str) -> ProcessOutcome:
        case.status = EmailCaseStatus.FAILED
        case.failure_code = code
        record(
            db,
            actor_id=None,
            action="EMAIL_PROCESSING_FAILED",
            entity="email_case",
            entity_id=case.id,
            details={"code": code},
        )
        await db.commit()
        return ProcessOutcome.FAILED

    def _mail_from_address(self) -> str:
        from email.utils import parseaddr

        return parseaddr(self.settings.mail_from)[1].lower()


async def mark_failed(sessionmaker: async_sessionmaker[AsyncSession], case_id: uuid.UUID, code: str) -> None:
    """Final failure of the processing step after retries (storage or database unavailable)."""
    async with sessionmaker() as db:
        case = await lock_case(db, case_id)
        if case is None or case.status != EmailCaseStatus.NEW:
            return
        case.status = EmailCaseStatus.FAILED
        case.failure_code = code
        record(
            db,
            actor_id=None,
            action="EMAIL_PROCESSING_FAILED",
            entity="email_case",
            entity_id=case.id,
            details={"code": code},
        )
        await db.commit()
