"""Isolation between students and permission boundaries on every request endpoint."""

import json

import pytest
from sqlalchemy import delete, insert

from app.users.models import Role, RolePermission
from tests.conftest import csrf
from tests.factories import PDF, attachment, make_catalog, make_enrollment, multipart, submit, transition


@pytest.fixture
async def two_students(harness):
    cat = await make_catalog(harness)
    alice, alice_user = await harness.logged_in()
    bob, bob_user = await harness.logged_in()
    alice_enrollment = await make_enrollment(harness, alice_user, cat)
    bob_enrollment = await make_enrollment(harness, bob_user, cat)
    async with alice, bob:
        res = await submit(
            alice, alice_enrollment.id, [(cat.with_attachment, 1)], [attachment(cat.with_attachment)]
        )
        assert res.status_code == 201
        bob.enrollment_id = bob_enrollment.id
        yield harness, cat, alice, bob, res.json(), alice_enrollment


async def test_student_never_sees_another_students_request(two_students):
    _, _, _, bob, req, _ = two_students
    rid, doc_id = req["id"], req["documents"][0]["id"]
    assert (await bob.get("/api/v1/requests")).json()["total"] == 0
    for res in (
        await bob.get(f"/api/v1/requests/{rid}"),
        await bob.get(f"/api/v1/requests/{rid}/messages"),
        await bob.get(f"/api/v1/requests/{rid}/documents/{doc_id}/download"),
        await bob.post(f"/api/v1/requests/{rid}/messages", files=multipart(body="hello"), headers=csrf(bob)),
        await bob.post(f"/api/v1/requests/{rid}/respond", files=multipart(body="hello"), headers=csrf(bob)),
        await bob.post(f"/api/v1/requests/{rid}/cancel", headers=csrf(bob)),
        await bob.post(f"/api/v1/requests/{rid}/messages/read", headers=csrf(bob)),
    ):
        assert res.status_code == 404, res.text  # same answer as for a request that does not exist


async def test_document_id_cannot_be_swapped_between_requests(two_students):
    _, cat, _, bob, alice_req, _ = two_students
    bob_req = (await submit(bob, bob.enrollment_id, [(cat.digital, 1)])).json()
    # Bob uses his own request id with Alice's document id.
    res = await bob.get(
        f"/api/v1/requests/{bob_req['id']}/documents/{alice_req['documents'][0]['id']}/download"
    )
    assert res.status_code == 404


async def test_student_cannot_use_admin_request_endpoints(two_students):
    _, _, alice, _, req, _ = two_students
    rid, doc_id = req["id"], req["documents"][0]["id"]
    h = csrf(alice)
    calls = [
        await alice.get("/api/v1/admin/requests"),
        await alice.get(f"/api/v1/admin/requests/{rid}"),
        await alice.get("/api/v1/admin/requests/assignees"),
        await alice.post(
            f"/api/v1/admin/requests/{rid}/transitions", json={"to_status": "APPROVED"}, headers=h
        ),
        await alice.post(
            f"/api/v1/admin/requests/{rid}/transitions",
            json={"to_status": "REJECTED", "comment": "x"},
            headers=h,
        ),
        await alice.post(f"/api/v1/admin/requests/{rid}/assign", json={"assignee_id": None}, headers=h),
        await alice.post(
            f"/api/v1/admin/requests/{rid}/documents",
            files=[("files", ("x.pdf", PDF, "application/pdf"))],
            headers=h,
        ),
        await alice.post(f"/api/v1/admin/requests/{rid}/messages", files=multipart(body="x"), headers=h),
        await alice.get(f"/api/v1/admin/requests/{rid}/documents/{doc_id}/download"),
        await alice.get("/api/v1/admin/enrollments"),
    ]
    assert [c.status_code for c in calls] == [403] * len(calls)
    # There is no student endpoint to set a status directly.
    direct = await alice.post(
        f"/api/v1/requests/{rid}/transitions", json={"to_status": "COMPLETED"}, headers=h
    )
    assert direct.status_code in (404, 405)
    assert (await alice.get(f"/api/v1/requests/{rid}")).json()["status"] == "RECEIVED"


async def test_admin_missing_a_permission_is_refused(two_students):
    """RBAC is data-driven: removing `requests.approve` from ADMIN immediately blocks approvals."""
    h, _, _, _, req, _ = two_students
    admin, _ = await h.logged_in(Role.ADMIN)
    async with admin:
        rid = req["id"]
        for status in ("IN_REVIEW", "PROCESSING"):
            assert (await transition(admin, rid, status)).status_code == 200
        async with await h.db() as db:
            await db.execute(
                delete(RolePermission).where(
                    RolePermission.role == Role.ADMIN, RolePermission.permission_code == "requests.approve"
                )
            )
            await db.commit()
        try:
            detail = (await admin.get(f"/api/v1/admin/requests/{rid}")).json()
            assert "APPROVED" not in detail["available_transitions"]
            res = await transition(admin, rid, "APPROVED")
            assert res.status_code == 403
        finally:
            async with await h.db() as db:
                await db.execute(
                    insert(RolePermission).values(role=Role.ADMIN, permission_code="requests.approve")
                )
                await db.commit()
        assert (await transition(admin, rid, "APPROVED")).status_code == 200


async def test_csrf_is_required_for_multipart_uploads(two_students):
    _, cat, alice, _, _, enrollment = two_students
    res = await alice.post(
        "/api/v1/requests",
        data={
            "payload": json.dumps(
                {"enrollment_id": str(enrollment.id), "items": [{"document_type_id": str(cat.digital.id)}]}
            )
        },
    )
    assert res.status_code == 403 and res.json()["error"]["code"] == "csrf_failed"


async def test_notifications_are_private(two_students):
    _, _, alice, bob, _, _ = two_students
    [note] = (await alice.get("/api/v1/notifications")).json()["items"]
    # Bob cannot mark Alice's notification as read (no effect on her data).
    assert (await bob.post(f"/api/v1/notifications/{note['id']}/read", headers=csrf(bob))).status_code == 204
    assert (await alice.get("/api/v1/notifications/unread-count")).json()["unread"] == 1
    assert (await bob.get("/api/v1/notifications")).json()["total"] == 0
    await alice.post("/api/v1/notifications/read-all", headers=csrf(alice))
    assert (await alice.get("/api/v1/notifications/unread-count")).json()["unread"] == 0
