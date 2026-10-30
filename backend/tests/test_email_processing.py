"""Email case processing on the real stack: GreenMail → IMAP poll → Celery email.process → Phase 3
attachment pipeline (S3 + ClamAV worker) → identification → Celery email.extract (scripted local LLM)."""

import uuid

import pytest
from sqlalchemy import func, select

from app.documents.models import Document, DocumentKind, ScanStatus
from app.emails.models import EmailCase, EmailCaseStatus, IdentificationMethod, ReviewConfidence
from app.requests.models import Request
from app.students.models import Student
from app.users.models import Role
from tests.conftest import TEST_DOMAIN
from tests.eicar import eicar_pdf
from tests.factories import PDF, make_catalog, make_enrollment, student_of
from tests.mailbox import AUTH_DMARC_FAIL, AUTH_PASS, build, deliver, new_mailbox


async def _docs(h, case_id) -> list[Document]:
    async with h.app.state.sessionmaker() as db:
        rows = await db.scalars(
            select(Document).where(Document.email_case_id == case_id).order_by(Document.created_at)
        )
        return list(rows.all())


async def unique_name(h, doc_type) -> str:
    """Gives a catalogue document type a name no other test catalogue uses (the AI matches names)."""
    from app.academic.models import DocumentType

    name = f"Releve special {uuid.uuid4().hex[:6]}"
    async with h.app.state.sessionmaker() as db:
        row = await db.get(DocumentType, doc_type.id)
        row.name_i18n = {"fr": name, "en": name, "ar": name}
        await db.commit()
    return name


async def _student(h, *, number: str | None = None, email: str | None = None):
    user = await h.create_user(Role.STUDENT, email=email)
    student = await student_of(h, user)
    if number:
        async with h.app.state.sessionmaker() as db:
            row = await db.get(Student, student.id)
            row.student_number = number
            await db.commit()
    return user, student


def _number() -> str:
    return "D" + str(uuid.uuid4().int)[:9]


# --- deterministic rules (before any AI) ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("headers", "sender", "rule"),
    [
        ({"Auto-Submitted": "auto-replied"}, f"prof@{TEST_DOMAIN}", "auto_reply"),
        ({"X-Autoreply": "yes"}, f"prof@{TEST_DOMAIN}", "auto_reply"),
        ({}, f"MAILER-DAEMON@{TEST_DOMAIN}", "bounce"),
    ],
)
async def test_auto_replies_and_bounces_are_ignored_before_any_ai(
    harness, make_settings, llm_server, headers, sender, rule
):
    token = uuid.uuid4().hex
    raw = build(sender=sender, to="x@y", headers=headers, body=f"Absent {token}")
    case = await deliver(harness, make_settings, raw)
    assert case.status == EmailCaseStatus.IGNORED and case.flags["ignored_rule"] == rule
    assert token not in str(llm_server["received"])  # never sent to the AI


async def test_message_from_our_own_mailbox_is_ignored(harness, make_settings):
    mailbox = new_mailbox()
    case = await deliver(harness, make_settings, build(sender=mailbox, to=mailbox), mailbox=mailbox)
    assert case.status == EmailCaseStatus.IGNORED and case.flags["ignored_rule"] == "own_address"


async def test_unparseable_message_fails_and_can_be_retried_by_staff(harness, make_settings):
    raw = b"Subject: no sender at all\r\nMessage-ID: <" + uuid.uuid4().hex.encode() + b"@x>\r\n\r\nbody\r\n"
    case = await deliver(harness, make_settings, raw)
    assert case.status == EmailCaseStatus.FAILED and case.failure_code == "parse_error"


# --- attachments: Phase 3 pipeline -------------------------------------------------------------------


async def test_attachments_go_through_validation_storage_and_antivirus(harness, make_settings, llm_server):
    llm_server["received"].clear()
    raw = build(
        sender=f"someone@{TEST_DOMAIN}",
        to="x@y",
        body="Voici mes pièces.",
        attachments=[
            ("releve.pdf", PDF, "application/pdf"),
            ("virus.pdf", eicar_pdf(), "application/pdf"),
            ("photo.png", PDF, "image/png"),  # PDF content declared as a PNG image
            ("setup.exe", b"MZ\x90\x00" + b"\x00" * 64, "application/octet-stream"),
            (
                "notes.docx",
                b"PK\x03\x04" + b"\x00" * 64,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        ],
    )
    case = await deliver(harness, make_settings, raw)
    assert case.status == EmailCaseStatus.NEEDS_REVIEW
    docs = {d.filename: d for d in await _docs(harness, case.id)}
    assert set(docs) == {"releve.pdf", "virus.pdf"}
    clean, infected = docs["releve.pdf"], docs["virus.pdf"]
    assert (
        clean.kind == DocumentKind.EMAIL_ATTACHMENT
        and clean.request_id is None
        and clean.uploaded_by_id is None
    )
    assert clean.scan_status == ScanStatus.CLEAN and clean.storage_key.startswith(
        f"tenants/default/emails/{case.id}/"
    )
    assert infected.scan_status == ScanStatus.INFECTED and infected.storage_key.startswith("quarantine/")
    rejected = {r["filename"]: r["code"] for r in case.flags["rejected_attachments"]}
    assert rejected == {
        "photo.png": "file_extension_mismatch",
        "setup.exe": "file_type_not_allowed",
        "notes.docx": "file_type_not_allowed",
    }
    # The infected file never reached the AI (only the email body is ever sent).
    sent = str([r["body"] for r in llm_server["received"]])
    assert "EICAR" not in sent and "releve.pdf" not in sent
    assert case.review_confidence == ReviewConfidence.LOW  # infected attachment


async def test_attachment_limits(harness, make_settings):
    from app.worker.context import WorkerContext
    from tests.mailbox import context_for, poll_until, send

    mailbox = new_mailbox()
    big = PDF + b"0" * 3000
    attachments = [("big.pdf", big, "application/pdf")] + [
        (f"p{i}.pdf", PDF, "application/pdf") for i in range(12)
    ]
    send(mailbox, build(sender=f"a@{TEST_DOMAIN}", to="x@y", attachments=attachments))
    results = await poll_until(context_for(make_settings, mailbox), 1)
    [case_id] = [c for r in results for c in r.new_case_ids]
    # Same processing code, stricter limits: 2 KB per file, 10 files per email.
    strict = WorkerContext(make_settings(max_upload_bytes=2048, email_max_attachments=10))
    assert (await strict.process(case_id)).value == "READY"
    async with harness.app.state.sessionmaker() as db:
        case = await db.get(EmailCase, case_id)
    docs = await _docs(harness, case_id)
    codes = [r["code"] for r in case.flags["rejected_attachments"]]
    assert len(docs) == 10 and case.flags["attachments_truncated"]
    assert codes.count("file_too_large") == 1 and codes.count("too_many_attachments") == 2


# --- identification ---------------------------------------------------------------------------------


async def test_institutional_address_with_favorable_authentication_identifies_the_student(
    harness, make_settings
):
    user, student = await _student(harness)
    case = await deliver(harness, make_settings, build(sender=user.email, to="x@y", auth=AUTH_PASS))
    assert case.student_id == student.id
    assert case.identification_method == IdentificationMethod.INSTITUTIONAL_EMAIL
    assert case.flags["authentication"] == "PASS"


@pytest.mark.parametrize(("auth", "verdict"), [(None, "ABSENT"), (AUTH_DMARC_FAIL, "FAIL")])
async def test_known_address_without_strong_proof_is_only_a_candidate(harness, make_settings, auth, verdict):
    user, student = await _student(harness)
    case = await deliver(harness, make_settings, build(sender=user.email, to="x@y", auth=auth))
    assert case.student_id is None and case.identification_method is None
    assert case.flags["authentication"] == verdict
    [candidate] = case.candidate_students
    assert candidate["student_id"] == str(student.id) and candidate["reasons"] == ["sender_email"]


async def test_forged_authentication_header_from_another_server_is_ignored(harness, make_settings):
    user, _ = await _student(harness)
    forged = AUTH_PASS.replace("mx.test-univ.ma", "mx.attacker.example")
    case = await deliver(harness, make_settings, build(sender=user.email, to="x@y", auth=forged))
    assert case.student_id is None and case.flags["authentication"] == "ABSENT"


async def test_personal_address_with_student_number_gives_a_candidate(harness, make_settings):
    number = _number()
    _, student = await _student(harness, number=number)
    raw = build(
        sender="sara.perso@gmail.example", to="x@y", body=f"Bonjour, mon numéro étudiant est {number}."
    )
    case = await deliver(harness, make_settings, raw)
    assert case.student_id is None
    [candidate] = case.candidate_students
    assert candidate["student_id"] == str(student.id) and candidate["reasons"] == ["student_number"]


async def test_unknown_sender_has_no_candidate(harness, make_settings):
    case = await deliver(
        harness, make_settings, build(sender="inconnu@example.org", to="x@y", auth=AUTH_PASS)
    )
    assert case.student_id is None and case.candidate_students == []
    assert case.status == EmailCaseStatus.NEEDS_REVIEW


async def test_reference_in_a_reply_is_detected(harness, make_settings):
    from tests.factories import submit

    cat = await make_catalog(harness)
    client, user = await harness.logged_in()
    enrollment = await make_enrollment(harness, user, cat)
    async with client:
        req = (await submit(client, enrollment.id, [(cat.digital, 1)])).json()
    raw = build(
        sender=user.email, to="x@y", subject=f"Re: [{req['reference']}] votre demande", auth=AUTH_PASS
    )
    case = await deliver(harness, make_settings, raw)
    assert case.detected_reference == req["reference"] and case.flags["is_reply"]
    assert "reference_sender_mismatch" not in case.flags
    other = await deliver(
        harness, make_settings, build(sender="x@example.org", to="y@z", subject=f"Re: {req['reference']}")
    )
    assert other.detected_reference == req["reference"] and other.flags["reference_sender_mismatch"]
    ghost = await deliver(
        harness, make_settings, build(sender="x@example.org", to="y@z", subject="Re: REQ-1999-000001")
    )
    assert ghost.detected_reference is None and ghost.flags["unknown_reference"] == "REQ-1999-000001"


# --- AI extraction ----------------------------------------------------------------------------------


async def test_complete_extraction_is_high_but_still_waits_for_a_human(harness, make_settings):
    cat = await make_catalog(harness)
    user, student = await _student(harness)
    await make_enrollment(harness, user, cat)
    name = await unique_name(harness, cat.digital)
    raw = build(
        sender=user.email,
        to="x@y",
        auth=AUTH_PASS,
        body=f"Bonjour,\nJe voudrais un {name} pour l'année {cat.year.label}, 2 exemplaires.\nMerci",
    )
    case = await deliver(harness, make_settings, raw)
    # HIGH is a completeness level for the reviewer: nothing happens automatically.
    assert case.status == EmailCaseStatus.NEEDS_REVIEW and case.review_confidence == ReviewConfidence.HIGH
    async with harness.app.state.sessionmaker() as db:
        assert (
            await db.scalar(select(func.count()).select_from(Request).where(Request.student_id == student.id))
            == 0
        )
        from app.ai.extraction import latest_extraction

        extraction = await latest_extraction(db, case.id)
    assert extraction.is_local_provider and extraction.raw_output_valid and extraction.rule_violations == []
    [item] = extraction.output["requested_documents"]
    assert item["document_type_code"] == cat.digital.code and item["quantity"] == 2
    assert extraction.output["matches"]["academic_year_id"] == str(cat.year.id)


async def test_missing_information_lowers_the_review_confidence(harness, make_settings):
    user, _ = await _student(harness)
    case = await deliver(
        harness,
        make_settings,
        build(sender=user.email, to="x@y", auth=AUTH_PASS, body="Bonjour, j'ai une question."),
    )
    assert case.status == EmailCaseStatus.NEEDS_REVIEW and case.review_confidence != ReviewConfidence.HIGH
    assert "document_type_found" in case.flags["review_reasons"]


@pytest.mark.parametrize(
    ("directive", "error"),
    [
        ("[[llm:invalid]]", "llm_invalid_output"),
        ("[[llm:tool]]", "llm_invalid_output"),
        ("[[llm:500]]", "llm_unavailable"),
        ("[[llm:timeout]]", "llm_unavailable"),
    ],
)
async def test_ai_failure_never_blocks_the_human_review(harness, make_settings, directive, error):
    case = await deliver(
        harness, make_settings, build(sender="a@example.org", to="x@y", body=f"Bonjour {directive}")
    )
    assert case.status == EmailCaseStatus.NEEDS_REVIEW
    assert case.flags["ai_failed"] is True and case.flags["ai_error"] == error
    assert case.review_confidence == ReviewConfidence.LOW


async def test_hallucinated_values_are_removed(harness, make_settings):
    case = await deliver(
        harness, make_settings, build(sender="a@example.org", to="x@y", body="Bonjour [[llm:hallucinate]]")
    )
    async with harness.app.state.sessionmaker() as db:
        from app.ai.extraction import latest_extraction

        extraction = await latest_extraction(db, case.id)
    reasons = {(v["field"], v["reason"]) for v in extraction.rule_violations}
    assert ("student_number", "not_in_text") in reasons
    assert ("requested_documents", "unknown_document_type") in reasons
    assert extraction.output["student_number"] is None
    assert all(i["document_type_code"] != "DIPLOME_FAKE" for i in extraction.output["requested_documents"])
    assert case.review_confidence == ReviewConfidence.LOW


async def test_case_processing_and_extraction_are_idempotent(harness, make_settings):
    from app.worker.context import worker_context

    case = await deliver(harness, make_settings, build(sender="a@example.org", to="x@y"))
    ctx = worker_context()
    assert (await ctx.process(case.id)).value == "SKIPPED"
    assert (await ctx.extract(case.id, final_attempt=True)).value == "SKIPPED"
