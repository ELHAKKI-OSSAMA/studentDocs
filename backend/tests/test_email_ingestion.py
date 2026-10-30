"""IMAP ingestion against a real IMAP server (GreenMail), real S3 and real PostgreSQL."""

import hashlib
import imaplib

import pytest
from sqlalchemy import func, select

from app.audit.models import AuditLog
from app.emails.models import EmailAccount, EmailCase, EmailCaseStatus, EmailMessage
from app.worker.context import worker_context
from app.worker.tasks import RedisLock, poll_mailbox_task
from tests.conftest import GREENMAIL_HOST, TEST_DOMAIN
from tests.mailbox import build, case_ids, context_for, new_mailbox, poll_until, send


async def _messages(h, mailbox: str) -> list[EmailMessage]:
    async with h.app.state.sessionmaker() as db:
        rows = await db.scalars(
            select(EmailMessage)
            .join(EmailAccount)
            .where(EmailAccount.address == mailbox)
            .order_by(EmailMessage.provider_uid)
        )
        return list(rows.all())


async def _account(h, mailbox: str) -> EmailAccount:
    async with h.app.state.sessionmaker() as db:
        return await db.scalar(select(EmailAccount).where(EmailAccount.address == mailbox))


def _imap_flags(mailbox: str) -> list[bytes]:
    conn = imaplib.IMAP4(GREENMAIL_HOST, 3143, timeout=10)
    try:
        conn.login(mailbox, "x")
        conn.select("INBOX", readonly=True)
        _, data = conn.fetch("1:*", "(FLAGS)")
        return [d for d in data if d]
    finally:
        conn.logout()


async def test_message_is_stored_raw_with_hash_and_case(harness, make_settings):
    mailbox = new_mailbox()
    raw = build(sender=f"sara@{TEST_DOMAIN}", to=mailbox, subject="Attestation")
    send(mailbox, raw)
    ctx = context_for(make_settings, mailbox)
    results = await poll_until(ctx, 1)
    [case_id] = case_ids(results)

    [message] = await _messages(harness, mailbox)
    stored = await harness.app.state.storage.get(message.raw_storage_key)
    assert hashlib.sha256(stored).hexdigest() == message.raw_sha256 and len(stored) == message.raw_size_bytes
    assert message.raw_storage_key.startswith("tenants/default/emails/raw/")
    assert message.from_address == f"sara@{TEST_DOMAIN}" and message.subject == "Attestation"
    assert message.to_addresses == [mailbox] and message.message_id_header
    assert message.received_at is not None and message.provider_uid >= 1
    async with harness.app.state.sessionmaker() as db:
        case = await db.get(EmailCase, case_id)
        assert case.status == EmailCaseStatus.NEW and case.email_message_id == message.id
        audit = await db.scalar(
            select(AuditLog).where(AuditLog.action == "EMAIL_RECEIVED", AuditLog.entity_id == str(case_id))
        )
        assert audit.details["sha256"] == message.raw_sha256 and "subject" not in audit.details
    account = await _account(harness, mailbox)
    assert account.last_seen_uid == message.provider_uid and account.last_error is None
    # Read-only: nothing was marked on the server (people can keep using the mailbox).
    assert all(b"\\Seen" not in f for f in _imap_flags(mailbox))


async def test_polling_twice_stores_once(harness, make_settings):
    mailbox = new_mailbox()
    send(mailbox, build(sender=f"a@{TEST_DOMAIN}", to=mailbox))
    ctx = context_for(make_settings, mailbox)
    await poll_until(ctx, 1)
    again = await ctx.poll()
    assert again.fetched == 0 and again.error is None
    assert len(await _messages(harness, mailbox)) == 1


async def test_same_message_id_is_skipped(harness, make_settings):
    mailbox = new_mailbox()
    raw = build(sender=f"a@{TEST_DOMAIN}", to=mailbox, message_id="<dup-1@test-univ.ma>")
    send(mailbox, raw)
    send(mailbox, raw)  # delivered twice: two UIDs, one Message-ID
    ctx = context_for(make_settings, mailbox)
    results = await poll_until(ctx, 2, seconds=3)
    assert sum(r.duplicates for r in results) == 1
    assert len(await _messages(harness, mailbox)) == 1
    assert (await _account(harness, mailbox)).last_seen_uid == 2  # the cursor passed both


async def test_same_content_without_message_id_is_ignored_as_duplicate(harness, make_settings):
    mailbox = new_mailbox()
    raw = build(sender=f"a@{TEST_DOMAIN}", to=mailbox, message_id=None)
    send(mailbox, raw)
    send(mailbox, raw)
    ctx = context_for(make_settings, mailbox)
    results = await poll_until(ctx, 2)
    messages = await _messages(harness, mailbox)
    assert len(messages) == 2 and messages[0].raw_sha256 == messages[1].raw_sha256
    assert len(case_ids(results)) == 1  # only the first one is processed
    async with harness.app.state.sessionmaker() as db:
        second = await db.scalar(select(EmailCase).where(EmailCase.email_message_id == messages[1].id))
    assert second.status == EmailCaseStatus.IGNORED and second.flags["ignored_rule"] == "duplicate"


async def test_uidvalidity_change_resets_the_cursor_without_duplicates(harness, make_settings):
    mailbox = new_mailbox()
    send(mailbox, build(sender=f"a@{TEST_DOMAIN}", to=mailbox))
    ctx = context_for(make_settings, mailbox)
    await poll_until(ctx, 1)
    async with harness.app.state.sessionmaker() as db:  # as if the mailbox had been rebuilt
        account = await db.scalar(select(EmailAccount).where(EmailAccount.address == mailbox))
        account.uid_validity = account.uid_validity + 1000
        account.last_seen_uid = 999
        await db.commit()
    result = await ctx.poll()
    assert result.uid_validity_reset and result.fetched == 0 and result.new_case_ids == []
    assert len(await _messages(harness, mailbox)) == 1
    async with harness.app.state.sessionmaker() as db:
        assert await db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "EMAIL_UIDVALIDITY_RESET", AuditLog.entity_id == str(account.id))
        )


async def test_unreachable_server_is_recorded_and_nothing_is_lost(harness, make_settings):
    mailbox = new_mailbox()
    send(mailbox, build(sender=f"a@{TEST_DOMAIN}", to=mailbox))
    down = context_for(make_settings, mailbox, imap_port=1, imap_timeout_seconds=2)
    result = await down.poll()
    assert result.error == "connection_failed" and result.fetched == 0
    account = await _account(harness, mailbox)
    assert account.last_error == "connection_failed" and account.last_error_at is not None
    async with harness.app.state.sessionmaker() as db:
        assert await db.scalar(
            select(AuditLog).where(
                AuditLog.action == "EMAIL_POLL_FAILED", AuditLog.entity_id == str(account.id)
            )
        )
    # The next poll (server back) gets the message.
    results = await poll_until(context_for(make_settings, mailbox), 1)
    assert len(case_ids(results)) == 1
    assert (await _account(harness, mailbox)).last_error is None


async def test_storage_failure_rolls_back_and_the_next_poll_retries(harness, make_settings, monkeypatch):
    mailbox = new_mailbox()
    send(mailbox, build(sender=f"a@{TEST_DOMAIN}", to=mailbox))
    ctx = context_for(make_settings, mailbox)

    async def broken(*args, **kwargs):
        raise OSError("storage down")

    monkeypatch.setattr(type(ctx.storage), "put", broken)
    result = await ctx.poll()
    assert result.error == "ingestion_error" and result.fetched == 0
    assert await _messages(harness, mailbox) == []
    assert (await _account(harness, mailbox)).last_seen_uid == 0
    monkeypatch.undo()
    results = await poll_until(ctx, 1)
    assert len(case_ids(results)) == 1 and len(await _messages(harness, mailbox)) == 1


async def test_too_large_message_is_not_downloaded(harness, make_settings):
    mailbox = new_mailbox()
    send(mailbox, build(sender=f"a@{TEST_DOMAIN}", to=mailbox, subject="Gros", body="x" * 20_000))
    ctx = context_for(make_settings, mailbox, email_max_bytes=5_000)
    results = await poll_until(ctx, 1)
    assert results[-1].too_large == 1 and case_ids(results) == []
    [message] = await _messages(harness, mailbox)
    assert message.provider_metadata["header_only"] is True and message.raw_size_bytes < 5_000
    assert message.subject == "Gros"
    async with harness.app.state.sessionmaker() as db:
        case = await db.scalar(select(EmailCase).where(EmailCase.email_message_id == message.id))
    assert case.status == EmailCaseStatus.FAILED and case.failure_code == "too_large"


async def test_concurrent_polls_are_prevented_by_a_redis_lock(harness):
    ctx = worker_context()
    settings = ctx.settings
    key = f"{settings.redis_key_prefix}email:poll:{ctx.mailbox_address}"
    holder = RedisLock(ctx.redis, key, 30)
    assert holder.acquire()
    try:
        assert not RedisLock(ctx.redis, key, 30).acquire()
        assert poll_mailbox_task.apply().get() == "locked"
    finally:
        holder.release()
    other = RedisLock(ctx.redis, key, 30)
    assert other.acquire()
    other.release()


@pytest.mark.parametrize("bad", [b"", b"\x00\x01garbage"])
async def test_garbage_messages_still_get_an_envelope(bad):
    from app.emails.parsing import parse_envelope

    env = parse_envelope(bad)
    assert env.from_address == "" and env.subject == ""
