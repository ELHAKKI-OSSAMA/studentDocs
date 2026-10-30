"""Inbound email test helpers: real SMTP delivery to GreenMail, real IMAP polling, real Celery tasks."""

import asyncio
import smtplib
import uuid
from email.message import EmailMessage
from email.utils import make_msgid

from sqlalchemy import select

from app.emails.models import EmailCase, EmailCaseStatus
from app.worker.context import WorkerContext
from app.worker.tasks import process_email_task
from tests.conftest import GREENMAIL_HOST, TEST_DOMAIN, TRUSTED_AUTHSERV_ID

SETTLED = (
    EmailCaseStatus.NEEDS_REVIEW,
    EmailCaseStatus.IGNORED,
    EmailCaseStatus.FAILED,
    EmailCaseStatus.CONVERTED,
    EmailCaseStatus.LINKED,
    EmailCaseStatus.DISMISSED,
)
AUTH_PASS = f"{TRUSTED_AUTHSERV_ID}; spf=pass smtp.mailfrom={TEST_DOMAIN}; dkim=pass header.d={TEST_DOMAIN}; dmarc=pass header.from={TEST_DOMAIN}"
AUTH_DMARC_FAIL = f"{TRUSTED_AUTHSERV_ID}; spf=fail smtp.mailfrom={TEST_DOMAIN}; dkim=none; dmarc=fail header.from={TEST_DOMAIN}"


def new_mailbox() -> str:
    return f"scolarite-{uuid.uuid4().hex[:10]}@{TEST_DOMAIN}"


def build(
    *,
    sender: str,
    to: str,
    subject: str = "Demande de document",
    body: str = "Bonjour,\nJe souhaite une attestation.\nMerci",
    html: str | None = None,
    auth: str | None = None,
    headers: dict | None = None,
    attachments: list[tuple[str, bytes, str]] | None = None,
    message_id: str | None | bool = True,
) -> bytes:
    msg = EmailMessage()
    if auth:
        msg["Authentication-Results"] = auth
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    if message_id is True:
        msg["Message-ID"] = make_msgid(domain=TEST_DOMAIN)
    elif message_id:
        msg["Message-ID"] = message_id
    for key, value in (headers or {}).items():
        msg[key] = value
    # base64 bodies: GreenMail does not undo SMTP dot-stuffing of quoted-printable lines starting with ".".
    msg.set_content(body, cte="base64")
    if html is not None:
        msg.add_alternative(html, subtype="html", cte="base64")
    for name, data, ctype in attachments or []:
        maintype, subtype = ctype.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return msg.as_bytes()


def send(to: str, raw: bytes, envelope_from: str = f"sender@{TEST_DOMAIN}") -> None:
    """Real SMTP delivery to GreenMail (the mailbox is created on first delivery)."""
    with smtplib.SMTP(GREENMAIL_HOST, 3025, timeout=10) as smtp:
        smtp.sendmail(envelope_from, [to], raw)


def context_for(make_settings, mailbox: str, **overrides) -> WorkerContext:
    return WorkerContext(make_settings(imap_username=mailbox, **overrides))


async def poll_until(ctx: WorkerContext, expected: int, seconds: float = 45.0):
    """Polls (real IMAP) until `expected` messages were stored in total (delivery is asynchronous)."""
    deadline = asyncio.get_running_loop().time() + seconds
    stored, results = 0, []
    while True:
        result = await ctx.poll()
        results.append(result)
        stored += result.fetched
        if stored >= expected or asyncio.get_running_loop().time() > deadline:
            return results
        await asyncio.sleep(0.3)


def case_ids(results) -> list[uuid.UUID]:
    return [cid for r in results for cid in r.new_case_ids]


async def wait_case(h, case_id, statuses=SETTLED, seconds: float = 60.0) -> EmailCase:
    deadline = asyncio.get_running_loop().time() + seconds
    while True:
        async with h.app.state.sessionmaker() as db:
            case = await db.get(EmailCase, case_id)
            if case is not None and case.status in statuses:
                return case
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(
                f"Email case {case_id} still {case.status if case else None} after {seconds}s"
            )
        await asyncio.sleep(0.25)


async def deliver(h, make_settings, raw: bytes, *, mailbox: str | None = None, settle: bool = True):
    """SMTP → GreenMail → poll → Celery email.process → (scans) → email.extract → settled case."""
    mailbox = mailbox or new_mailbox()
    send(mailbox, raw)
    ctx = context_for(make_settings, mailbox)
    results = await poll_until(ctx, 1)
    ids = case_ids(results)
    assert len(ids) == 1, results
    settings = h.app.state.settings
    process_email_task.apply_async(args=[str(ids[0])], queue=settings.email_queue)
    if settle:
        return await wait_case(h, ids[0])
    return ids[0]


async def case_by_message(h, sha: str):
    from app.emails.models import EmailMessage

    async with h.app.state.sessionmaker() as db:
        return await db.scalar(select(EmailCase).join(EmailMessage).where(EmailMessage.raw_sha256 == sha))
