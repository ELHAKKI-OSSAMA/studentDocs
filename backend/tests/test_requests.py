"""Request creation rules and the full administrative workflow, through the real API, DB and S3."""

import asyncio
import re

import pytest
from sqlalchemy import func, select, text

from app.audit.models import AuditLog
from app.notifications.models import Notification
from app.students.models import EnrollmentStatus
from app.users.models import Role
from tests.conftest import csrf
from tests.factories import (
    EXE,
    PDF,
    PNG,
    attachment,
    make_catalog,
    make_enrollment,
    multipart,
    submit,
    transition,
)


@pytest.fixture
async def setup(harness):
    catalog = await make_catalog(harness)
    student, user = await harness.logged_in()
    enrollment = await make_enrollment(harness, user, catalog)
    admin, admin_user = await harness.logged_in(Role.ADMIN)
    async with student, admin:
        yield harness, catalog, student, user, enrollment, admin, admin_user


# --- creation -----------------------------------------------------------------------------------------


async def test_create_request_with_supporting_document(setup):
    h, cat, student, user, enrollment, *_ = setup
    res = await submit(
        student,
        enrollment.id,
        [(cat.digital, 2), (cat.with_attachment, 1)],
        [attachment(cat.with_attachment, "../convention signée.pdf")],
        reason="Stage de fin d'études",
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert re.fullmatch(r"REQ-\d{4}-\d{6}", body["reference"])
    assert body["status"] == "RECEIVED" and body["source"] == "WEB"
    assert [h["to_status"] for h in body["history"]] == ["SUBMITTED", "RECEIVED"]
    assert body["history"][1]["actor_role"] == "SYSTEM"
    assert {i["document_type"]["code"]: i["quantity"] for i in body["items"]} == {
        cat.digital.code: 2,
        cat.with_attachment.code: 1,
    }
    assert body["can_cancel"] and not body["can_respond"] and body["available_transitions"] == []
    [doc] = body["documents"]
    assert doc["kind"] == "ATTACHMENT" and doc["filename"] == "convention_signée.pdf"
    assert doc["scan_status"] == "NOT_SCANNED"  # no antivirus yet — never claimed otherwise

    # The file really is in object storage and comes back byte-for-byte to its owner.
    res = await student.get(f"/api/v1/requests/{body['id']}/documents/{doc['id']}/download")
    assert res.status_code == 200 and res.content == PDF
    assert res.headers["content-type"] == "application/pdf"
    assert res.headers["content-disposition"].startswith("attachment;")
    assert res.headers["cache-control"] == "private, no-store"

    async with await h.db() as db:
        notes = (await db.scalars(select(Notification).where(Notification.user_id == user.id))).all()
        assert [n.type for n in notes] == ["REQUEST_RECEIVED"]
        actions = set(
            (await db.scalars(select(AuditLog.action).where(AuditLog.actor_user_id == user.id))).all()
        )
        assert {"REQUEST_CREATED", "DOCUMENT_UPLOADED", "DOCUMENT_DOWNLOADED"} <= actions


async def test_supporting_document_is_mandatory(setup):
    _, cat, student, _, enrollment, *_ = setup
    res = await submit(student, enrollment.id, [(cat.with_attachment, 1)])
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "attachment_required"
    assert res.json()["error"]["details"]["document_type_ids"] == [str(cat.with_attachment.id)]
    # Nothing was created.
    assert (await student.get("/api/v1/requests")).json()["total"] == 0


async def test_upload_validation(setup, make_settings, harness_for):
    _, cat, student, _, enrollment, *_ = setup
    exe = await submit(
        student,
        enrollment.id,
        [(cat.with_attachment, 1)],
        [attachment(cat.with_attachment, "cv.pdf", EXE, "application/pdf")],
    )
    assert exe.json()["error"]["code"] == "file_type_not_allowed"
    png = await submit(
        student,
        enrollment.id,
        [(cat.with_attachment, 1)],
        [attachment(cat.with_attachment, "scan.png", PNG, "image/png")],
    )
    assert png.status_code == 201 and png.json()["documents"][0]["mime_type"] == "image/png"
    stray = await submit(student, enrollment.id, [(cat.digital, 1)], [attachment(cat.with_attachment)])
    assert stray.json()["error"]["code"] == "unexpected_file"
    bad_field = await submit(
        student, enrollment.id, [(cat.digital, 1)], [("evil", ("x.pdf", PDF, "application/pdf"))]
    )
    assert bad_field.json()["error"]["code"] == "unexpected_file"


async def test_file_size_limit(make_settings, harness_for):
    async for h in harness_for(make_settings(max_upload_bytes=1024)):
        await h.ensure_domain()
        cat = await make_catalog(h)
        client, user = await h.logged_in()
        enrollment = await make_enrollment(h, user, cat)
        async with client:
            res = await submit(
                client,
                enrollment.id,
                [(cat.with_attachment, 1)],
                [attachment(cat.with_attachment, content=PDF + b"0" * 2048)],
            )
        assert res.status_code == 422 and res.json()["error"]["code"] == "file_too_large"


async def test_business_rules(setup):
    _, cat, student, _, enrollment, *_ = setup

    def code(res):
        return res.json()["error"]["code"]

    assert (
        code(await submit(student, enrollment.id, [(cat.other_category_only, 1)]))
        == "document_type_not_allowed"
    )
    assert code(await submit(student, enrollment.id, [(cat.pickup, 2)])) == "quantity_exceeded"
    dup = await submit(student, enrollment.id, [(cat.digital, 1), (cat.digital, 1)])
    assert dup.status_code == 422 and code(dup) == "validation_error"
    empty = await submit(student, enrollment.id, [])
    assert empty.status_code == 422
    not_json = await student.post("/api/v1/requests", files=multipart(payload="{oops"), headers=csrf(student))
    assert code(not_json) == "validation_error"
    as_json = await student.post("/api/v1/requests", json={}, headers=csrf(student))
    assert as_json.status_code == 415


@pytest.mark.parametrize("status", [EnrollmentStatus.PENDING, EnrollmentStatus.REJECTED])
async def test_unverified_enrollment_cannot_back_a_request(harness, status):
    cat = await make_catalog(harness)
    client, user = await harness.logged_in()
    enrollment = await make_enrollment(harness, user, cat, status)
    async with client:
        res = await submit(client, enrollment.id, [(cat.digital, 1)])
    assert res.status_code == 422 and res.json()["error"]["code"] == "enrollment_not_verified"


async def test_references_are_unique_under_concurrency(setup):
    _, cat, student, _, enrollment, *_ = setup
    results = await asyncio.gather(*(submit(student, enrollment.id, [(cat.digital, 1)]) for _ in range(6)))
    assert all(r.status_code == 201 for r in results), [r.text for r in results]
    refs = [r.json()["reference"] for r in results]
    assert len(set(refs)) == 6


# --- cancellation ---------------------------------------------------------------------------------------


async def test_student_cancels_only_until_received(setup):
    _, cat, student, _, enrollment, admin, _ = setup
    first = (await submit(student, enrollment.id, [(cat.digital, 1)])).json()
    res = await student.post(f"/api/v1/requests/{first['id']}/cancel", headers=csrf(student))
    assert res.status_code == 200 and res.json()["status"] == "CANCELLED" and res.json()["closed_at"]
    again = await student.post(f"/api/v1/requests/{first['id']}/cancel", headers=csrf(student))
    assert again.status_code == 409

    second = (await submit(student, enrollment.id, [(cat.digital, 1)])).json()
    assert (await transition(admin, second["id"], "IN_REVIEW")).status_code == 200
    detail = (await student.get(f"/api/v1/requests/{second['id']}")).json()
    assert detail["can_cancel"] is False
    res = await student.post(f"/api/v1/requests/{second['id']}/cancel", headers=csrf(student))
    assert res.status_code == 409 and res.json()["error"]["code"] == "transition_not_allowed"
    assert (await student.get(f"/api/v1/requests/{second['id']}")).json()["status"] == "IN_REVIEW"


# --- full workflow ----------------------------------------------------------------------------------------


async def test_full_digital_workflow(setup):
    h, cat, student, user, enrollment, admin, admin_user = setup
    req = (await submit(student, enrollment.id, [(cat.digital, 1)])).json()
    rid = req["id"]

    # Admin sees it, assigns it to themself.
    listed = (await admin.get("/api/v1/admin/requests", params={"q": req["reference"]})).json()
    assert [r["id"] for r in listed["items"]] == [rid]
    assert listed["items"][0]["student"]["email"] == user.email
    res = await admin.post(
        f"/api/v1/admin/requests/{rid}/assign", json={"assignee_id": str(admin_user.id)}, headers=csrf(admin)
    )
    assert res.json()["assigned_to"]["id"] == str(admin_user.id)
    mine = (await admin.get("/api/v1/admin/requests", params={"assigned": "me"})).json()
    assert rid in [r["id"] for r in mine["items"]]

    # No shortcut.
    jump = await transition(admin, rid, "COMPLETED")
    assert jump.status_code == 409 and jump.json()["error"]["code"] == "transition_not_allowed"

    assert (await transition(admin, rid, "IN_REVIEW")).json()["status"] == "IN_REVIEW"
    # Information request: the message is mandatory.
    no_msg = await transition(admin, rid, "NEEDS_INFORMATION")
    assert no_msg.status_code == 422 and no_msg.json()["error"]["code"] == "message_required"
    res = await transition(admin, rid, "NEEDS_INFORMATION", "Merci de joindre votre carte d'étudiant.")
    assert res.json()["status"] == "NEEDS_INFORMATION"

    detail = (await student.get(f"/api/v1/requests/{rid}")).json()
    assert detail["can_respond"] and detail["unread_messages"] == 1
    thread = (await student.get(f"/api/v1/requests/{rid}/messages")).json()
    assert (
        thread[0]["kind"] == "INFORMATION_REQUEST" and thread[0]["author_name"] == ""
    )  # staff stays anonymous

    # Student answers with a file → back to review automatically.
    res = await student.post(
        f"/api/v1/requests/{rid}/respond",
        files=multipart([("files", ("carte.png", PNG, "image/png"))], body="Voici ma carte."),
        headers=csrf(student),
    )
    assert res.status_code == 201, res.text
    assert res.json()["kind"] == "INFORMATION_RESPONSE" and res.json()["attachments"][0]["kind"] == "MESSAGE"
    assert (await student.get(f"/api/v1/requests/{rid}")).json()["status"] == "IN_REVIEW"
    # Responding twice is impossible: nothing is being asked any more.
    twice = await student.post(
        f"/api/v1/requests/{rid}/respond", files=multipart(body="x"), headers=csrf(student)
    )
    assert twice.status_code == 409

    staff_view = (await admin.get(f"/api/v1/admin/requests/{rid}")).json()
    assert staff_view["unread_messages"] == 1
    await admin.post(f"/api/v1/admin/requests/{rid}/messages/read", headers=csrf(admin))
    assert (await admin.get(f"/api/v1/admin/requests/{rid}")).json()["unread_messages"] == 0
    assert (await student.get(f"/api/v1/requests/{rid}/messages")).json()[0]["read_at"] is None

    for status in ("PROCESSING", "APPROVED"):
        assert (await transition(admin, rid, status)).json()["status"] == status

    # DOCUMENT_AVAILABLE requires the final document.
    early = await transition(admin, rid, "DOCUMENT_AVAILABLE")
    assert early.status_code == 422 and early.json()["error"]["code"] == "issued_document_required"
    up = await admin.post(
        f"/api/v1/admin/requests/{rid}/documents",
        files=[("files", ("attestation.pdf", PDF, "application/pdf"))],
        headers=csrf(admin),
    )
    assert up.status_code == 201 and up.json()[0]["kind"] == "ISSUED"
    issued_id = up.json()[0]["id"]

    # Hidden from the student until it is made available.
    assert issued_id not in [
        d["id"] for d in (await student.get(f"/api/v1/requests/{rid}")).json()["documents"]
    ]
    hidden = await student.get(f"/api/v1/requests/{rid}/documents/{issued_id}/download")
    assert hidden.status_code == 404

    assert (await transition(admin, rid, "DOCUMENT_AVAILABLE")).json()["status"] == "DOCUMENT_AVAILABLE"
    res = await student.get(f"/api/v1/requests/{rid}/documents/{issued_id}/download")
    assert res.status_code == 200 and res.content == PDF
    docs = (await student.get("/api/v1/requests/documents")).json()
    assert [d["id"] for d in docs] == [issued_id] and docs[0]["reference"] == req["reference"]

    done = await transition(admin, rid, "COMPLETED")
    body = done.json()
    assert body["status"] == "COMPLETED" and body["closed_at"] and body["available_transitions"] == []
    assert [x["to_status"] for x in body["history"]] == [
        "SUBMITTED",
        "RECEIVED",
        "IN_REVIEW",
        "NEEDS_INFORMATION",
        "IN_REVIEW",
        "PROCESSING",
        "APPROVED",
        "DOCUMENT_AVAILABLE",
        "COMPLETED",
    ]
    # Closed: no more messages.
    closed = await student.post(
        f"/api/v1/requests/{rid}/messages", files=multipart(body="merci"), headers=csrf(student)
    )
    assert closed.status_code == 409

    summary = (await student.get("/api/v1/requests/summary")).json()
    assert summary["completed"] == 1
    notes = (await student.get("/api/v1/notifications")).json()["items"]
    assert {n["type"] for n in notes} >= {"REQUEST_RECEIVED", "INFORMATION_REQUESTED", "STATUS_CHANGED"}


async def test_pickup_workflow_and_delivery_guards(setup):
    _, cat, student, _, enrollment, admin, _ = setup
    rid = (await submit(student, enrollment.id, [(cat.pickup, 1)])).json()["id"]
    for status in ("IN_REVIEW", "PROCESSING", "APPROVED"):
        await transition(admin, rid, status)
    wrong = await transition(admin, rid, "DOCUMENT_AVAILABLE")
    assert wrong.json()["error"]["code"] == "delivery_mode_mismatch"
    assert (await transition(admin, rid, "READY_FOR_PICKUP")).json()["status"] == "READY_FOR_PICKUP"
    assert (await transition(admin, rid, "COMPLETED")).json()["status"] == "COMPLETED"

    digital = (await submit(student, enrollment.id, [(cat.digital, 1)])).json()["id"]
    for status in ("IN_REVIEW", "PROCESSING", "APPROVED"):
        await transition(admin, digital, status)
    assert (await transition(admin, digital, "READY_FOR_PICKUP")).json()["error"][
        "code"
    ] == "delivery_mode_mismatch"


async def test_rejection(setup):
    _, cat, student, _, enrollment, admin, _ = setup
    rid = (await submit(student, enrollment.id, [(cat.digital, 1)])).json()["id"]
    no_reason = await transition(admin, rid, "REJECTED")
    assert no_reason.status_code == 422 and no_reason.json()["error"]["code"] == "message_required"
    res = await transition(admin, rid, "REJECTED", "Dossier incomplet")
    assert res.json()["status"] == "REJECTED" and res.json()["status_reason"] == "Dossier incomplet"
    assert (await student.get(f"/api/v1/requests/{rid}")).json()["status_reason"] == "Dossier incomplet"
    # Approved requests can no longer be rejected; terminal states have no exit.
    assert (await transition(admin, rid, "IN_REVIEW")).status_code == 409

    rid2 = (await submit(student, enrollment.id, [(cat.digital, 1)])).json()["id"]
    for status in ("IN_REVIEW", "PROCESSING", "APPROVED"):
        await transition(admin, rid2, status)
    assert (await transition(admin, rid2, "REJECTED", "trop tard")).status_code == 409


async def test_assignment_rules(setup):
    h, cat, student, user, enrollment, admin, _ = setup
    rid = (await submit(student, enrollment.id, [(cat.digital, 1)])).json()["id"]
    to_student = await admin.post(
        f"/api/v1/admin/requests/{rid}/assign", json={"assignee_id": str(user.id)}, headers=csrf(admin)
    )
    assert to_student.status_code == 422 and to_student.json()["error"]["code"] == "invalid_assignee"
    other_admin = await h.create_user(Role.ADMIN)
    res = await admin.post(
        f"/api/v1/admin/requests/{rid}/assign", json={"assignee_id": str(other_admin.id)}, headers=csrf(admin)
    )
    assert res.json()["assigned_to"]["id"] == str(other_admin.id)
    assignees = (await admin.get("/api/v1/admin/requests/assignees")).json()
    assert str(other_admin.id) in [a["id"] for a in assignees] and str(user.id) not in [
        a["id"] for a in assignees
    ]
    unassign = await admin.post(
        f"/api/v1/admin/requests/{rid}/assign", json={"assignee_id": None}, headers=csrf(admin)
    )
    assert unassign.json()["assigned_to"] is None
    async with await h.db() as db:
        n = await db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == other_admin.id, Notification.type == "REQUEST_ASSIGNED")
        )
        assert n == 1


async def test_admin_filters(setup):
    h, cat, student, _, enrollment, admin, _ = setup
    rid = (await submit(student, enrollment.id, [(cat.digital, 1)])).json()["id"]

    async def ids(**params):
        return [r["id"] for r in (await admin.get("/api/v1/admin/requests", params=params)).json()["items"]]

    assert rid in await ids(category_id=str(cat.category.id))
    assert rid in await ids(branch_id=str(cat.branch.id))
    assert rid in await ids(academic_year_id=str(cat.year.id))
    assert rid in await ids(status="RECEIVED")
    assert rid not in await ids(status="IN_REVIEW")
    assert rid not in await ids(category_id=str(cat.other_category.id))
    assert rid in await ids(assigned="unassigned")
    bad = await admin.get("/api/v1/admin/requests", params={"status": "NOPE"})
    assert bad.status_code == 422

    stats = (await admin.get("/api/v1/admin/dashboard")).json()
    assert stats["requests_open"] >= 1 and stats["requests_by_status"]["RECEIVED"] >= 1


async def test_status_history_is_append_only(setup):
    h, cat, student, _, enrollment, *_ = setup
    rid = (await submit(student, enrollment.id, [(cat.digital, 1)])).json()["id"]
    async with await h.db() as db:
        with pytest.raises(Exception, match="append-only"):
            await db.execute(
                text("UPDATE request_status_history SET comment = 'x' WHERE request_id = :r"), {"r": rid}
            )
        await db.rollback()
        with pytest.raises(Exception, match="append-only"):
            await db.execute(text("DELETE FROM audit_logs"))
        await db.rollback()
