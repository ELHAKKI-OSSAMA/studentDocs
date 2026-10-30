"""Human review API: permissions, raw .eml, correction, conversion (atomic), link, dismiss / ignore /
reopen / retry, concurrency. Real stack: GreenMail, IMAP, Celery, S3, ClamAV, scripted local LLM."""

import asyncio

import pytest
from sqlalchemy import func, select

from app.audit.models import AuditLog
from app.documents.models import Document, ScanStatus
from app.emails.models import EmailCase, EmailCaseReview, EmailCaseStatus, ReviewDecision
from app.messages.models import RequestMessage
from app.notifications.models import Notification
from app.requests.models import Request, RequestSource, RequestStatus
from app.users.models import Role, RolePermission
from tests.conftest import csrf
from tests.eicar import eicar_pdf
from tests.factories import PDF, make_catalog, make_enrollment, student_of, submit, transition
from tests.mailbox import AUTH_PASS, build, deliver

BASE = "/api/v1/admin/emails"


@pytest.fixture
async def world(harness, make_settings):
    """A student (verified enrollment), an admin, and an email case from that student."""
    cat = await make_catalog(harness)
    student_client, user = await harness.logged_in()
    admin, admin_user = await harness.logged_in(Role.ADMIN)
    enrollment = await make_enrollment(harness, user, cat)
    student = await student_of(harness, user)
    async with student_client, admin:
        yield harness, cat, student_client, admin, enrollment, user, student, make_settings


async def _case(world, **build_kw) -> EmailCase:
    h, _, _, _, _, user, _, make_settings = world
    values = {"sender": user.email, "to": "scolarite@test-univ.ma", "auth": AUTH_PASS} | build_kw
    return await deliver(h, make_settings, build(**values))


async def _requests_of(h, student_id) -> int:
    async with h.app.state.sessionmaker() as db:
        return await db.scalar(
            select(func.count()).select_from(Request).where(Request.student_id == student_id)
        )


def _convert_body(cat, enrollment, student, case, **kw) -> dict:
    return {
        "student_id": str(student.id),
        "enrollment_id": str(enrollment.id),
        "items": [{"document_type_id": str(cat.digital.id), "quantity": 1}],
        "reason": "Demande reçue par email",
        "version": case["version"],
    } | kw


# --- reading & permissions ----------------------------------------------------------------------------


async def test_list_detail_and_no_storage_key(world):
    h, _, _, admin, _, user, student, _ = world
    case = await _case(
        world,
        subject="Attestation SVP",
        html='<p>Bonjour<script>alert(1)</script><img src="https://t.example/p.gif"></p>',
    )
    page = (await admin.get(BASE, params={"q": user.email})).json()
    assert [i["id"] for i in page["items"]] == [str(case.id)]
    item = page["items"][0]
    assert item["status"] == "NEEDS_REVIEW" and item["student"]["id"] == str(student.id)
    detail = (await admin.get(f"{BASE}/{case.id}")).json()
    assert "<script" not in (detail["body_html"] or "") and "<img" not in (detail["body_html"] or "")
    assert detail["can_convert"] and detail["can_read_raw"]
    assert "storage_key" not in str(detail) and "raw_storage_key" not in str(detail)
    filtered = (await admin.get(BASE, params={"status": "IGNORED", "q": user.email})).json()
    assert filtered["items"] == []


async def test_students_and_anonymous_users_never_reach_email_cases(world):
    h, _, student_client, _, _, _, _, _ = world
    case = await _case(world)
    routes = [
        ("GET", BASE),
        ("GET", f"{BASE}/stats"),
        ("GET", f"{BASE}/{case.id}"),
        ("GET", f"{BASE}/{case.id}/raw"),
        ("POST", f"{BASE}/{case.id}/convert"),
        ("POST", f"{BASE}/{case.id}/link"),
        ("POST", f"{BASE}/{case.id}/dismiss"),
        ("POST", f"{BASE}/{case.id}/student"),
        ("PUT", f"{BASE}/{case.id}/extraction"),
    ]
    async with h.client() as anonymous:
        for method, path in routes:
            assert (
                await student_client.request(method, path, headers=csrf(student_client), json={})
            ).status_code == 403
            assert (await anonymous.request(method, path, json={})).status_code in (401, 403)


async def test_raw_eml_download_is_audited_and_never_inline(world):
    h, _, _, admin, _, _, _, _ = world
    case = await _case(world, subject="Brut")
    res = await admin.get(f"{BASE}/{case.id}/raw")
    assert res.status_code == 200 and res.headers["content-type"].startswith("message/rfc822")
    assert res.headers["content-disposition"].startswith("attachment;")
    assert res.headers["x-content-type-options"] == "nosniff"
    assert b"Subject: Brut" in res.content
    async with h.app.state.sessionmaker() as db:
        assert await db.scalar(
            select(AuditLog).where(
                AuditLog.action == "EMAIL_RAW_DOWNLOADED", AuditLog.entity_id == str(case.id)
            )
        )
    # Super admins have it too; the permission is dedicated (removing it from ADMIN closes the route).
    sa, _ = await h.logged_in(Role.SUPER_ADMIN)
    async with sa:
        assert (await sa.get(f"{BASE}/{case.id}/raw")).status_code == 200
    async with h.app.state.sessionmaker() as db:
        await db.execute(
            RolePermission.__table__.delete().where(
                RolePermission.role == Role.ADMIN, RolePermission.permission_code == "emails.read_raw"
            )
        )
        await db.commit()
    try:
        fresh, _ = await h.logged_in(Role.ADMIN)
        async with fresh:
            assert (await fresh.get(f"{BASE}/{case.id}/raw")).status_code == 403
            assert (await fresh.get(f"{BASE}/{case.id}")).json()["can_read_raw"] is False
    finally:
        async with h.app.state.sessionmaker() as db:
            db.add(RolePermission(role=Role.ADMIN, permission_code="emails.read_raw"))
            await db.commit()


async def test_attachment_download_follows_phase3_rules(world):
    h, _, _, admin, _, _, _, _ = world
    case = await _case(
        world, attachments=[("ok.pdf", PDF, "application/pdf"), ("bad.pdf", eicar_pdf(), "application/pdf")]
    )
    docs = {d["filename"]: d for d in (await admin.get(f"{BASE}/{case.id}")).json()["documents"]}
    assert docs["ok.pdf"]["can_download"] and not docs["bad.pdf"]["can_download"]
    ok = await admin.get(f"{BASE}/{case.id}/documents/{docs['ok.pdf']['id']}/download")
    assert ok.status_code == 200 and ok.content.startswith(b"%PDF")
    bad = await admin.get(f"{BASE}/{case.id}/documents/{docs['bad.pdf']['id']}/download")
    assert bad.status_code == 409 and bad.json()["error"]["code"] == "document_not_available"


async def test_error_attachment_can_be_rescanned(world):
    h, _, _, admin, _, _, _, _ = world
    case = await _case(world, attachments=[("ok.pdf", PDF, "application/pdf")])
    [doc] = (await admin.get(f"{BASE}/{case.id}")).json()["documents"]
    async with h.app.state.sessionmaker() as db:  # a past ClamAV outage
        row = await db.get(Document, doc["id"])
        row.scan_status, row.scan_detail = ScanStatus.ERROR, "scanner_unavailable"
        await db.commit()
    assert (await admin.get(f"{BASE}/{case.id}/documents/{doc['id']}/download")).status_code == 409
    res = await admin.post(f"{BASE}/{case.id}/documents/{doc['id']}/rescan", headers=csrf(admin))
    assert res.status_code == 200 and res.json()["scan_status"] == "SCANNING"
    for _ in range(240):
        if (await admin.get(f"{BASE}/{case.id}")).json()["documents"][0]["scan_status"] == "CLEAN":
            break
        await asyncio.sleep(0.25)
    assert (await admin.get(f"{BASE}/{case.id}/documents/{doc['id']}/download")).status_code == 200


# --- correction, association --------------------------------------------------------------------------


async def test_correction_is_stored_next_to_the_ai_proposal(world):
    h, cat, _, admin, enrollment, _, _, _ = world
    case = await _case(world)
    body = {
        "requested_documents": [{"document_type_id": str(cat.digital.id), "quantity": 2}],
        "enrollment_id": str(enrollment.id),
        "comment": "ajout quantité",
    }
    res = await admin.put(f"{BASE}/{case.id}/extraction", json=body, headers=csrf(admin))
    assert res.status_code == 200, res.text
    detail = res.json()
    assert detail["correction"]["requested_documents"][0]["quantity"] == 2
    assert detail["extraction"] is not None  # the AI proposal is kept unchanged
    async with h.app.state.sessionmaker() as db:
        audit = await db.scalar(
            select(AuditLog).where(
                AuditLog.action == "EMAIL_EXTRACTION_CORRECTED", AuditLog.entity_id == str(case.id)
            )
        )
    assert "requested_documents" in audit.details["fields"] and "ajout" not in str(audit.details)
    assert (
        await admin.put(f"{BASE}/{case.id}/extraction", json={"bogus": 1}, headers=csrf(admin))
    ).status_code == 422


async def test_staff_associates_a_candidate_student(world):
    h, _, _, admin, _, user, student, make_settings = world
    case = await deliver(
        h, make_settings, build(sender=user.email, to="x@y")
    )  # no authentication: candidate only
    assert case.student_id is None
    res = await admin.post(
        f"{BASE}/{case.id}/student", json={"student_id": str(student.id)}, headers=csrf(admin)
    )
    assert res.status_code == 200
    assert (
        res.json()["student"]["id"] == str(student.id)
        and res.json()["identification_method"] == "ADMIN_MANUAL"
    )


# --- conversion ---------------------------------------------------------------------------------------


async def test_conversion_creates_the_request_atomically(world):
    h, cat, student_client, admin, enrollment, user, student, _ = world
    case = await _case(world, attachments=[("piece.pdf", PDF, "application/pdf")])
    detail = (await admin.get(f"{BASE}/{case.id}")).json()
    [doc] = detail["documents"]
    body = _convert_body(
        cat,
        enrollment,
        student,
        detail,
        items=[
            {"document_type_id": str(cat.with_attachment.id), "quantity": 1, "attachment_ids": [doc["id"]]}
        ],
    )
    res = await admin.post(f"{BASE}/{case.id}/convert", json=body, headers=csrf(admin))
    assert res.status_code == 201, res.text
    req = res.json()
    assert req["source"] == "EMAIL" and req["status"] == "RECEIVED"
    assert req["reference"].startswith("REQ-") and len(req["reference"]) == 15
    [attached] = req["documents"]
    assert attached["id"] == doc["id"] and attached["kind"] == "EMAIL_ATTACHMENT"
    async with h.app.state.sessionmaker() as db:
        row = await db.get(Document, doc["id"])
        assert row.request_id is not None and row.email_case_id == case.id  # same row, both links
        converted = await db.get(EmailCase, case.id)
        assert converted.status == EmailCaseStatus.CONVERTED and str(converted.linked_request_id) == req["id"]
        assert await db.scalar(
            select(Notification).where(Notification.user_id == user.id, Notification.request_id == req["id"])
        )
        actions = set(
            (
                await db.scalars(
                    select(AuditLog.action).where(AuditLog.entity_id.in_([str(case.id), req["id"]]))
                )
            ).all()
        )
        assert {"EMAIL_CASE_CONVERTED", "REQUEST_CREATED"} <= actions
        request = await db.get(Request, req["id"])
        assert request.source == RequestSource.EMAIL
    # The student sees it, with the email attachment, and the Phase 2 workflow applies.
    own = await student_client.get(f"/api/v1/requests/{req['id']}")
    assert own.status_code == 200 and len(own.json()["documents"]) == 1
    assert (await transition(admin, req["id"], "IN_REVIEW")).status_code == 200
    # Converting again is impossible.
    again = await admin.post(
        f"{BASE}/{case.id}/convert", json=body | {"version": converted.version}, headers=csrf(admin)
    )
    assert again.status_code == 409


@pytest.mark.parametrize(
    "failure",
    [
        "enrollment_not_verified",
        "document_type_not_allowed",
        "attachment_required",
        "quantity_exceeded",
        "infected",
    ],
)
async def test_failed_conversion_leaves_nothing_behind(world, failure):
    from app.students.models import EnrollmentStatus

    h, cat, _, admin, enrollment, user, student, _ = world
    attachments = [("bad.pdf", eicar_pdf(), "application/pdf")] if failure == "infected" else None
    case = await _case(world, attachments=attachments)
    detail = (await admin.get(f"{BASE}/{case.id}")).json()
    body = _convert_body(cat, enrollment, student, detail)
    expected = failure
    if failure == "enrollment_not_verified":
        async with h.app.state.sessionmaker() as db:
            from app.students.models import StudentEnrollment

            row = await db.get(StudentEnrollment, enrollment.id)
            row.status = EnrollmentStatus.PENDING
            await db.commit()
    elif failure == "document_type_not_allowed":
        body["items"] = [{"document_type_id": str(cat.other_category_only.id), "quantity": 1}]
    elif failure == "attachment_required":
        body["items"] = [{"document_type_id": str(cat.with_attachment.id), "quantity": 1}]
    elif failure == "quantity_exceeded":
        body["items"] = [{"document_type_id": str(cat.digital.id), "quantity": 9}]
    else:
        [doc] = detail["documents"]
        body["items"] = [
            {"document_type_id": str(cat.with_attachment.id), "quantity": 1, "attachment_ids": [doc["id"]]}
        ]
        expected = "attachment_not_clean"
    res = await admin.post(f"{BASE}/{case.id}/convert", json=body, headers=csrf(admin))
    assert res.status_code == 422 and res.json()["error"]["code"] == expected, res.text
    assert await _requests_of(h, student.id) == 0
    after = (await admin.get(f"{BASE}/{case.id}")).json()
    assert after["status"] == "NEEDS_REVIEW" and after["version"] == detail["version"]
    async with h.app.state.sessionmaker() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(Document)
                .where(Document.email_case_id == case.id, Document.request_id.is_not(None))
            )
            == 0
        )


async def test_concurrent_conversions_create_a_single_request(world):
    h, cat, _, admin, enrollment, _, student, _ = world
    case = await _case(world)
    detail = (await admin.get(f"{BASE}/{case.id}")).json()
    body = _convert_body(cat, enrollment, student, detail)
    second, _ = await h.logged_in(Role.ADMIN)
    async with second:
        a, b = await asyncio.gather(
            admin.post(f"{BASE}/{case.id}/convert", json=body, headers=csrf(admin)),
            second.post(f"{BASE}/{case.id}/convert", json=body, headers=csrf(second)),
        )
    assert sorted([a.status_code, b.status_code]) == [201, 409]
    assert await _requests_of(h, student.id) == 1


async def test_conversion_requires_its_permission(world):
    h, cat, _, admin, enrollment, _, student, _ = world
    case = await _case(world)
    detail = (await admin.get(f"{BASE}/{case.id}")).json()
    async with h.app.state.sessionmaker() as db:
        await db.execute(
            RolePermission.__table__.delete().where(
                RolePermission.role == Role.ADMIN, RolePermission.permission_code == "emails.convert"
            )
        )
        await db.commit()
    try:
        limited, _ = await h.logged_in(Role.ADMIN)
        async with limited:
            res = await limited.post(
                f"{BASE}/{case.id}/convert",
                json=_convert_body(cat, enrollment, student, detail),
                headers=csrf(limited),
            )
            assert res.status_code == 403
    finally:
        async with h.app.state.sessionmaker() as db:
            db.add(RolePermission(role=Role.ADMIN, permission_code="emails.convert"))
            await db.commit()
    assert await _requests_of(h, student.id) == 0


# --- link ---------------------------------------------------------------------------------------------


async def test_reply_with_reference_is_linked_to_the_request(world):
    h, cat, student_client, admin, enrollment, user, _, make_settings = world
    req = (await submit(student_client, enrollment.id, [(cat.digital, 1)])).json()
    assert (await transition(admin, req["id"], "IN_REVIEW")).status_code == 200
    assert (
        await transition(admin, req["id"], "NEEDS_INFORMATION", "Merci d'envoyer votre relevé")
    ).status_code == 200
    raw = build(
        sender=user.email,
        to="x@y",
        auth=AUTH_PASS,
        subject=f"Re: [{req['reference']}] information demandée",
        body="Voici le relevé demandé.",
        attachments=[("releve.pdf", PDF, "application/pdf")],
    )
    case = await deliver(h, make_settings, raw)
    detail = (await admin.get(f"{BASE}/{case.id}")).json()
    assert detail["reference_request"]["id"] == req["id"]
    [doc] = detail["documents"]
    res = await admin.post(
        f"{BASE}/{case.id}/link",
        json={
            "request_id": req["id"],
            "attachment_ids": [doc["id"]],
            "as_information_response": True,
            "version": detail["version"],
        },
        headers=csrf(admin),
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "IN_REVIEW"
    thread = (await student_client.get(f"/api/v1/requests/{req['id']}/messages")).json()
    last = thread[-1]
    assert last["author_side"] == "STUDENT" and "Voici le relevé demandé." in last["body"]
    assert [a["id"] for a in last["attachments"]] == [doc["id"]]
    assert (await admin.get(f"{BASE}/{case.id}")).json()["status"] == "LINKED"
    # A linked case cannot be converted nor linked again.
    again = await admin.post(
        f"{BASE}/{case.id}/link", json={"request_id": req["id"], "version": 99}, headers=csrf(admin)
    )
    assert again.status_code == 409


async def test_link_requires_the_same_student(world):
    h, cat, student_client, admin, enrollment, _, _, make_settings = world
    req = (await submit(student_client, enrollment.id, [(cat.digital, 1)])).json()
    case = await deliver(
        h, make_settings, build(sender="autre@example.org", to="x@y", subject=f"Re: {req['reference']}")
    )
    detail = (await admin.get(f"{BASE}/{case.id}")).json()
    res = await admin.post(
        f"{BASE}/{case.id}/link",
        json={"request_id": req["id"], "version": detail["version"]},
        headers=csrf(admin),
    )
    assert res.status_code == 422 and res.json()["error"]["code"] == "student_mismatch"
    async with h.app.state.sessionmaker() as db:
        assert (
            await db.scalar(
                select(func.count()).select_from(RequestMessage).where(RequestMessage.request_id == req["id"])
            )
            == 0
        )


# --- dismiss / ignore / reopen / retry ----------------------------------------------------------------


async def test_dismiss_ignore_reopen_and_forbidden_transitions(world):
    h, cat, _, admin, enrollment, _, student, _ = world
    case = await _case(world)
    assert (
        await admin.post(f"{BASE}/{case.id}/dismiss", json={"reason": " "}, headers=csrf(admin))
    ).status_code == 422
    res = await admin.post(f"{BASE}/{case.id}/dismiss", json={"reason": "Publicité"}, headers=csrf(admin))
    assert (
        res.status_code == 200
        and res.json()["status"] == "DISMISSED"
        and res.json()["dismiss_reason"] == "Publicité"
    )
    convert = await admin.post(
        f"{BASE}/{case.id}/convert",
        json=_convert_body(cat, enrollment, student, res.json()),
        headers=csrf(admin),
    )
    assert convert.status_code == 409 and convert.json()["error"]["code"] == "email_case_status_conflict"
    reopened = await admin.post(f"{BASE}/{case.id}/reopen", json={"comment": "erreur"}, headers=csrf(admin))
    assert reopened.json()["status"] == "NEEDS_REVIEW" and reopened.json()["dismiss_reason"] is None
    ignored = await admin.post(f"{BASE}/{case.id}/ignore", json={"reason": "Doublon"}, headers=csrf(admin))
    assert ignored.json()["status"] == "IGNORED"
    async with h.app.state.sessionmaker() as db:
        decisions = (
            await db.scalars(
                select(EmailCaseReview.decision)
                .where(EmailCaseReview.email_case_id == case.id)
                .order_by(EmailCaseReview.created_at)
            )
        ).all()
    assert decisions == [ReviewDecision.DISMISS, ReviewDecision.REOPEN, ReviewDecision.IGNORE]


async def test_failed_case_retry(world):
    h, _, _, admin, _, _, _, make_settings = world
    raw = b"Subject: no sender\r\nMessage-ID: <retry-" + str(id(world)).encode() + b"@x>\r\n\r\nbody\r\n"
    case = await deliver(h, make_settings, raw)
    assert case.status == EmailCaseStatus.FAILED
    res = await admin.post(f"{BASE}/{case.id}/retry", headers=csrf(admin))
    assert res.status_code == 200 and res.json()["status"] in ("NEW", "FAILED")
    for _ in range(120):
        detail = (await admin.get(f"{BASE}/{case.id}")).json()
        if detail["status"] == "FAILED":
            break
        await asyncio.sleep(0.25)
    assert detail["status"] == "FAILED" and detail["failure_code"] == "parse_error"


async def test_reextract_runs_the_ai_again(world):
    h, _, _, admin, _, _, _, _ = world
    case = await _case(world)
    res = await admin.post(f"{BASE}/{case.id}/reextract", headers=csrf(admin))
    assert res.status_code == 200 and res.json()["status"] == "AI_PROCESSING"
    for _ in range(120):
        detail = (await admin.get(f"{BASE}/{case.id}")).json()
        if detail["status"] == "NEEDS_REVIEW":
            break
        await asyncio.sleep(0.25)
    assert detail["status"] == "NEEDS_REVIEW"
    async with h.app.state.sessionmaker() as db:
        from app.ai.models import AiExtraction

        assert (
            await db.scalar(
                select(func.count()).select_from(AiExtraction).where(AiExtraction.email_case_id == case.id)
            )
            == 2
        )


async def test_stats(world):
    _, _, _, admin, _, _, _, _ = world
    await _case(world)
    stats = (await admin.get(f"{BASE}/stats")).json()
    assert (
        stats["awaiting_review"] >= 1
        and stats["ai_provider"] == "openai_compatible"
        and stats["ai_is_local"] is True
    )


async def test_request_status_unchanged_by_email(world):
    """Sanity: nothing in the email flow touches existing requests without a human action."""
    h, cat, student_client, _, enrollment, user, _, make_settings = world
    req = (await submit(student_client, enrollment.id, [(cat.digital, 1)])).json()
    await deliver(
        h,
        make_settings,
        build(
            sender=user.email,
            to="x@y",
            auth=AUTH_PASS,
            subject=f"Re: [{req['reference']}] annulez ma demande",
        ),
    )
    async with h.app.state.sessionmaker() as db:
        assert (await db.get(Request, req["id"])).status == RequestStatus.RECEIVED
