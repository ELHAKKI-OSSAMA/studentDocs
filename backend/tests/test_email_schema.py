"""Phase 4 schema: constraints, append-only tables and permissions, checked on the real database."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.documents.models import Document, DocumentKind, ScanStatus
from app.emails.models import EmailAccount, EmailCase, EmailCaseStatus, EmailMessage
from app.users.models import Role, RolePermission

EMAIL_PERMS = {"emails.read", "emails.read_raw", "emails.process", "emails.convert", "emails.dismiss"}


async def _message(db, account: EmailAccount, uid: int, message_id: str | None = None) -> EmailMessage:
    msg = EmailMessage(
        account_id=account.id,
        uid_validity=1,
        provider_uid=uid,
        message_id_header=message_id,
        from_address="someone@example.org",
        subject="s",
        received_at=datetime.now(UTC),
        raw_storage_key=f"tenants/default/emails/raw/{uuid.uuid4().hex}",
        raw_sha256="0" * 64,
        raw_size_bytes=10,
    )
    db.add(msg)
    await db.flush()
    return msg


@pytest.fixture
async def account(harness):
    async with harness.app.state.sessionmaker() as db:
        acc = EmailAccount(address=f"box-{uuid.uuid4().hex[:8]}@test-univ.ma")
        db.add(acc)
        await db.commit()
        return acc


async def test_permissions_seeded_for_staff_only(harness):
    async with harness.app.state.sessionmaker() as db:
        rows = (await db.scalars(select(RolePermission))).all()
    by_role: dict[Role, set[str]] = {}
    for r in rows:
        by_role.setdefault(r.role, set()).add(r.permission_code)
    assert EMAIL_PERMS <= by_role[Role.ADMIN]
    assert EMAIL_PERMS | {"email_accounts.manage"} <= by_role[Role.SUPER_ADMIN]
    assert not {p for p in by_role[Role.STUDENT] if p.startswith("email")}


async def test_message_idempotence_constraints(harness, account):
    async with harness.app.state.sessionmaker() as db:
        await _message(db, account, 1, "<a@x>")
        await db.commit()
    for uid, mid in ((1, None), (2, "<a@x>")):  # same UID, then same Message-ID
        async with harness.app.state.sessionmaker() as db:
            with pytest.raises(IntegrityError):
                await _message(db, account, uid, mid)
    async with harness.app.state.sessionmaker() as db:  # no Message-ID: several are allowed
        await _message(db, account, 3)
        await _message(db, account, 4)
        await db.commit()


async def test_messages_reviews_and_extractions_are_append_only(harness, account):
    async with harness.app.state.sessionmaker() as db:
        msg = await _message(db, account, 10)
        await db.commit()
    for sql in (
        "UPDATE email_messages SET subject = 'x' WHERE id = :id",
        "DELETE FROM email_messages WHERE id = :id",
    ):
        async with harness.app.state.sessionmaker() as db:
            with pytest.raises(DBAPIError, match="append-only|not allowed|forbid"):
                await db.execute(text(sql), {"id": msg.id})


async def test_case_status_constraints(harness, account):
    async with harness.app.state.sessionmaker() as db:
        msg = await _message(db, account, 20)
        case = EmailCase(email_message_id=msg.id)
        db.add(case)
        await db.commit()
    for status in ("CONVERTED", "LINKED", "DISMISSED"):  # need a request / a student / a reason
        async with harness.app.state.sessionmaker() as db:
            with pytest.raises(IntegrityError):
                await db.execute(
                    text("UPDATE email_cases SET status = :s WHERE id = :id"), {"s": status, "id": case.id}
                )
    async with harness.app.state.sessionmaker() as db:
        with pytest.raises(IntegrityError):
            await db.execute(text("UPDATE email_cases SET status = 'BOGUS' WHERE id = :id"), {"id": case.id})
    async with harness.app.state.sessionmaker() as db:
        assert (await db.get(EmailCase, case.id)).status == EmailCaseStatus.NEW


async def test_documents_need_an_owner_and_an_uploader(harness, account):
    async with harness.app.state.sessionmaker() as db:
        msg = await _message(db, account, 30)
        case = EmailCase(email_message_id=msg.id)
        db.add(case)
        await db.commit()

    def doc(**kw) -> Document:
        values = {
            "kind": DocumentKind.EMAIL_ATTACHMENT,
            "filename": "a.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 1,
            "sha256": "0" * 64,
            "storage_key": f"k/{uuid.uuid4().hex}",
            "scan_status": ScanStatus.SCANNING,
        } | kw
        return Document(**values)

    async with harness.app.state.sessionmaker() as db:  # email attachment: case, no request, no uploader
        db.add(doc(email_case_id=case.id))
        await db.commit()
    async with harness.app.state.sessionmaker() as db:  # no owner at all
        db.add(doc())
        with pytest.raises(IntegrityError, match="ck_documents_owner"):
            await db.commit()
    async with harness.app.state.sessionmaker() as db:  # only email attachments may lack an uploader
        db.add(doc(kind=DocumentKind.ATTACHMENT, email_case_id=case.id))
        with pytest.raises(IntegrityError, match="ck_documents_uploader"):
            await db.commit()
