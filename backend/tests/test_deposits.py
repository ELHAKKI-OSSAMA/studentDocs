"""Deposited originals: only what a student deposited can be withdrawn; the staff sees the student's history."""

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.academic.models import DeliveryMode, DocumentType
from app.audit.models import AuditLog
from app.users.models import Role
from tests.conftest import csrf
from tests.factories import attachment, make_catalog, make_enrollment, student_of, submit, wait_scanned


@pytest.fixture
async def setup(harness):
    catalog = await make_catalog(harness)
    async with harness.app.state.sessionmaker() as db:
        bac = DocumentType(
            code=f"RETRAIT_{uuid.uuid4().hex[:8].upper()}",
            name_i18n={"fr": "Retrait du bac"},
            delivery_mode=DeliveryMode.PICKUP,
            requires_attachment=False,
            requires_deposit=True,
            max_quantity=1,
            processing_days=5,
            is_active=True,
        )
        db.add(bac)
        await db.commit()
    student, user = await harness.logged_in()
    enrollment = await make_enrollment(harness, user, catalog)
    profile = await student_of(harness, user)
    admin, _ = await harness.logged_in(Role.ADMIN)
    async with student, admin:
        yield harness, catalog, bac, student, enrollment, profile, admin


async def _deposit(admin, student_id, doc_type, **extra):
    body = {"document_type_id": str(doc_type.id), "deposited_on": "2022-09-15"} | extra
    return await admin.post(f"/api/v1/admin/students/{student_id}/deposits", json=body, headers=csrf(admin))


async def test_withdrawal_requires_an_open_deposit(setup):
    h, cat, bac, student, enrollment, profile, admin = setup

    # Nothing deposited: the request is refused, whatever the client shows.
    res = await submit(student, enrollment.id, [(bac, 1)])
    assert res.status_code == 422 and res.json()["error"]["code"] == "document_not_deposited"
    assert (await student.get("/api/v1/students/me/deposits")).json() == []

    res = await _deposit(admin, profile.id, bac, note="Original, dossier 42")
    assert res.status_code == 201, res.text
    deposit = res.json()
    assert deposit["document_type"]["id"] == str(bac.id) and deposit["returned_at"] is None

    [mine] = (await student.get("/api/v1/students/me/deposits")).json()
    assert mine["id"] == deposit["id"]
    res = await submit(student, enrollment.id, [(bac, 1)])
    assert res.status_code == 201, res.text

    # Returned: it can no longer be requested, but stays in the staff history.
    res = await admin.post(
        f"/api/v1/admin/students/{profile.id}/deposits/{deposit['id']}/return", headers=csrf(admin)
    )
    assert res.status_code == 200 and res.json()["returned_at"]
    assert (await student.get("/api/v1/students/me/deposits")).json() == []
    res = await submit(student, enrollment.id, [(bac, 1)])
    assert res.json()["error"]["code"] == "document_not_deposited"
    [history] = (await admin.get(f"/api/v1/admin/students/{profile.id}/deposits")).json()
    assert history["returned_at"]

    async with await h.db() as db:
        actions = (
            await db.scalars(
                select(AuditLog.action)
                .where(AuditLog.entity_id == str(profile.id))
                .order_by(AuditLog.created_at)
            )
        ).all()
    assert actions == ["DEPOSIT_RECORDED", "DEPOSIT_RETURNED"]


async def test_ordinary_documents_need_no_deposit(setup):
    _, cat, _, student, enrollment, *_ = setup
    res = await submit(student, enrollment.id, [(cat.digital, 1)])
    assert res.status_code == 201, res.text


async def test_deposit_rules(setup):
    _, cat, bac, student, _, profile, admin = setup
    # Only a deposit-type document, never in the future, never twice while open.
    res = await _deposit(admin, profile.id, cat.digital)
    assert res.status_code == 422
    future = (date.today() + timedelta(days=1)).isoformat()
    assert (await _deposit(admin, profile.id, bac, deposited_on=future)).status_code == 422
    assert (await _deposit(admin, profile.id, bac)).status_code == 201
    res = await _deposit(admin, profile.id, bac)
    assert res.status_code == 409 and res.json()["error"]["code"] == "deposit_exists"
    # A student can neither record a deposit nor read the staff endpoints.
    assert (await _deposit(student, profile.id, bac)).status_code == 403
    assert (await student.get(f"/api/v1/admin/students/{profile.id}/documents")).status_code == 403
    assert (
        await admin.post(
            f"/api/v1/admin/students/{uuid.uuid4()}/deposits/{uuid.uuid4()}/return", headers=csrf(admin)
        )
    ).status_code == 404


async def test_staff_sees_student_history(setup):
    _, cat, _, student, enrollment, profile, admin = setup
    res = await submit(student, enrollment.id, [(cat.with_attachment, 1)], [attachment(cat.with_attachment)])
    assert res.status_code == 201, res.text
    request = res.json()
    await wait_scanned(student, f"/api/v1/requests/{request['id']}")

    page = (await admin.get("/api/v1/admin/requests", params={"student_id": str(profile.id)})).json()
    assert [r["id"] for r in page["items"]] == [request["id"]] and page["total"] == 1

    [doc] = (await admin.get(f"/api/v1/admin/students/{profile.id}/documents")).json()
    assert doc["request_id"] == request["id"] and doc["reference"] == request["reference"]
    assert doc["kind"] == "ATTACHMENT" and doc["can_download"] is True
    assert "storage_key" not in str(doc)
    res = await admin.get(f"/api/v1/admin/requests/{request['id']}/documents/{doc['id']}/download")
    assert res.status_code == 200
