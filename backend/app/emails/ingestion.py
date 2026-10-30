"""Polling: mailbox → raw .eml in private storage → email_messages + email_cases (NEW).

One transaction per message: the message row, its case and the account cursor are committed together,
so a crash re-processes at most the message in flight, and the UNIQUE constraints absorb it.

Idempotence, in order:
1. IMAP: UNIQUE(account, UIDVALIDITY, UID) and the `last_seen_uid` cursor;
2. RFC: UNIQUE(account, Message-ID) — an already known Message-ID is skipped (no new case);
3. content: the same raw SHA-256 without Message-ID → a case IGNORED as duplicate, linked to the first.
"""

import asyncio
import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.service import record
from app.documents.storage import ObjectStorage
from app.emails.authentication import evaluate
from app.emails.models import EmailAccount, EmailCase, EmailCaseStatus, EmailMessage
from app.emails.parsing import parse_envelope
from app.emails.provider import EmailProvider, MailboxError, MailboxSession, MessageInfo

logger = logging.getLogger(__name__)


@dataclass
class PollResult:
    fetched: int = 0
    duplicates: int = 0
    too_large: int = 0
    error: str | None = None
    uid_validity_reset: bool = False
    # Cases to process once committed (NEW ones; IGNORED duplicates need nothing more).
    new_case_ids: list[uuid.UUID] = field(default_factory=list)


async def ensure_account(db: AsyncSession, address: str, folder: str) -> EmailAccount:
    address = address.strip().lower()
    account = await db.scalar(select(EmailAccount).where(EmailAccount.address == address))
    if account is None:
        account = EmailAccount(address=address, folder=folder, is_active=True)
        db.add(account)
        await db.commit()
    return account


class IngestionService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        storage: ObjectStorage,
        provider: EmailProvider,
        *,
        max_bytes: int,
        batch: int,
        trusted_authserv_ids: list[str],
    ) -> None:
        self.sessionmaker = sessionmaker
        self.storage = storage
        self.provider = provider
        self.max_bytes = max_bytes
        self.batch = batch
        self.trusted_authserv_ids = trusted_authserv_ids

    async def poll(self, address: str, folder: str) -> PollResult:
        result = PollResult()
        async with self.sessionmaker() as db:
            account = await ensure_account(db, address, folder)
            account_id = account.id
            if not account.is_active:
                return result
        try:
            # imaplib is blocking: the whole session runs in a worker thread, one message at a time,
            # each message being committed from the event loop before the next one is fetched.
            loop = asyncio.get_running_loop()
            await asyncio.to_thread(self._run_session, loop, account_id, result)
        except MailboxError as exc:
            result.error = exc.code
        except Exception:
            # Storage or database failure: the message in flight was rolled back and its UID not passed,
            # so the next poll fetches it again.
            logger.exception("Mailbox ingestion failed")
            result.error = "ingestion_error"
        await self._record_poll(account_id, result)
        return result

    # --- IMAP side (thread) ---------------------------------------------------------------------

    def _run_session(self, loop, account_id: uuid.UUID, result: PollResult) -> None:
        def call(coro):
            return asyncio.run_coroutine_threadsafe(coro, loop).result()

        with self.provider.session() as session:
            cursor = call(self._cursor(account_id, session.uid_validity, result))
            for uid in session.uids_after(cursor)[: self.batch]:
                info = session.info(uid)
                if info is None:  # expunged between SEARCH and FETCH: skip it
                    call(self._advance(account_id, session.uid_validity, uid))
                    continue
                raw, truncated = self._download(session, info)
                if raw is None:
                    call(self._advance(account_id, session.uid_validity, uid))
                    continue
                call(self._store(account_id, session.uid_validity, info, raw, truncated, result))

    def _download(self, session: MailboxSession, info: MessageInfo) -> tuple[bytes | None, bool]:
        if info.size > self.max_bytes:
            # Not downloaded: only the header is kept, the case becomes FAILED / too_large.
            return session.fetch_header(info.uid), True
        return session.fetch(info.uid), False

    # --- database side (event loop) -------------------------------------------------------------

    async def _cursor(self, account_id: uuid.UUID, uid_validity: int, result: PollResult) -> int:
        async with self.sessionmaker() as db:
            account = await db.get(EmailAccount, account_id, with_for_update=True)
            if account.uid_validity is not None and account.uid_validity != uid_validity:
                # UIDs of the previous validity mean nothing anymore: start again from the beginning,
                # Message-ID and content hashes prevent processing a message twice.
                record(
                    db,
                    actor_id=None,
                    action="EMAIL_UIDVALIDITY_RESET",
                    entity="email_account",
                    entity_id=account.id,
                    details={"previous": account.uid_validity, "current": uid_validity},
                )
                account.last_seen_uid = 0
                result.uid_validity_reset = True
            account.uid_validity = uid_validity
            cursor = account.last_seen_uid
            await db.commit()
            return cursor

    async def _advance(self, account_id: uuid.UUID, uid_validity: int, uid: int) -> None:
        async with self.sessionmaker() as db:
            account = await db.get(EmailAccount, account_id, with_for_update=True)
            if account.uid_validity == uid_validity and uid > account.last_seen_uid:
                account.last_seen_uid = uid
            await db.commit()

    async def _store(
        self,
        account_id: uuid.UUID,
        uid_validity: int,
        info: MessageInfo,
        raw: bytes,
        truncated: bool,
        result: PollResult,
    ) -> None:
        envelope = parse_envelope(raw)
        sha = hashlib.sha256(raw).hexdigest()
        async with self.sessionmaker() as db:
            account = await db.get(EmailAccount, account_id, with_for_update=True)
            known = await db.scalar(
                select(EmailMessage.id).where(
                    EmailMessage.account_id == account_id,
                    EmailMessage.uid_validity == uid_validity,
                    EmailMessage.provider_uid == info.uid,
                )
            )
            if known is None and envelope.message_id:
                known = await db.scalar(
                    select(EmailMessage.id).where(
                        EmailMessage.account_id == account_id,
                        EmailMessage.message_id_header == envelope.message_id,
                    )
                )
                if known is not None:
                    result.duplicates += 1
                    record(
                        db,
                        actor_id=None,
                        action="EMAIL_DUPLICATE_SKIPPED",
                        entity="email_message",
                        entity_id=known,
                        details={"reason": "message_id", "uid": info.uid},
                    )
            if known is not None:
                account.last_seen_uid = max(account.last_seen_uid, info.uid)
                await db.commit()
                return

            duplicate_of = None
            if not envelope.message_id:
                duplicate_of = await db.scalar(
                    select(EmailCase.id)
                    .join(EmailMessage, EmailCase.email_message_id == EmailMessage.id)
                    .where(EmailMessage.account_id == account_id, EmailMessage.raw_sha256 == sha)
                    .limit(1)
                )

            key = self.storage.new_raw_email_key()
            await self.storage.put(key, raw, "message/rfc822")
            try:
                message = EmailMessage(
                    account_id=account_id,
                    uid_validity=uid_validity,
                    provider_uid=info.uid,
                    message_id_header=envelope.message_id,
                    in_reply_to=envelope.in_reply_to,
                    references_header=envelope.references,
                    from_address=envelope.from_address,
                    from_name=envelope.from_name,
                    to_addresses=envelope.to,
                    cc_addresses=envelope.cc,
                    subject=envelope.subject,
                    sent_at=envelope.sent_at,
                    received_at=info.internal_date or datetime.now(UTC),
                    raw_storage_key=key,
                    raw_sha256=sha,
                    raw_size_bytes=len(raw),
                    auth_results=evaluate(
                        envelope.auth_headers, envelope.from_address, self.trusted_authserv_ids
                    ),
                    provider_metadata={
                        "uid": info.uid,
                        "flags": list(info.flags),
                        "rfc822_size": info.size,
                        "header_only": truncated,
                    },
                )
                db.add(message)
                await db.flush()
                case = EmailCase(email_message_id=message.id, status=EmailCaseStatus.NEW, flags={})
                if truncated:
                    case.status = EmailCaseStatus.FAILED
                    case.failure_code = "too_large"
                    result.too_large += 1
                elif duplicate_of is not None:
                    case.status = EmailCaseStatus.IGNORED
                    case.flags = {"duplicate_of": str(duplicate_of), "ignored_rule": "duplicate"}
                    result.duplicates += 1
                db.add(case)
                await db.flush()
                record(
                    db,
                    actor_id=None,
                    action="EMAIL_RECEIVED",
                    entity="email_case",
                    entity_id=case.id,
                    details={
                        "sha256": sha,
                        "size_bytes": len(raw),
                        "status": case.status.value,
                        "uid": info.uid,
                    },
                )
                account.last_seen_uid = max(account.last_seen_uid, info.uid)
                await db.commit()
            except BaseException:
                await db.rollback()
                await self.storage.delete_quietly([key])
                raise
            result.fetched += 1
            if case.status == EmailCaseStatus.NEW:
                result.new_case_ids.append(case.id)

    async def _record_poll(self, account_id: uuid.UUID, result: PollResult) -> None:
        async with self.sessionmaker() as db:
            account = await db.get(EmailAccount, account_id)
            now = datetime.now(UTC)
            account.last_polled_at = now
            if result.error:
                account.last_error, account.last_error_at = result.error, now
                record(
                    db,
                    actor_id=None,
                    action="EMAIL_POLL_FAILED",
                    entity="email_account",
                    entity_id=account.id,
                    details={"error": result.error, "fetched": result.fetched},
                )
                logger.warning("Mailbox poll failed: %s (%d message(s) stored)", result.error, result.fetched)
            else:
                account.last_success_at, account.last_error = now, None
            await db.commit()
