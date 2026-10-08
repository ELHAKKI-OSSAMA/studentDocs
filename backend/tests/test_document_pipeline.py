"""Antivirus pipeline against the real services: PostgreSQL, Redis, Celery, SeaweedFS (S3) and ClamAV.

Uploads are scanned by a real Celery worker (see `scan_worker` in conftest.py). Scenarios that need a
document to stay SCANNING use an app whose scan queue nobody consumes, then drive `scan_document`
directly with the real scanner (or with an unreachable / broken one).
"""

import asyncio
import re
import socket
import threading
import uuid

import httpx
import pytest
from sqlalchemy import delete, func, insert, select

from app.audit.models import AuditLog
from app.documents.models import Document, ScanStatus
from app.documents.scanner import ClamdScanner, ScannerUnavailable
from app.documents.scanning import ScanOutcome, scan_document
from app.notifications.models import Notification
from app.users.models import Role, RolePermission
from app.worker.tasks import enqueue_pending_scans, scan_document_task
from tests.conftest import csrf
from tests.eicar import eicar_pdf
from tests.factories import PDF, attachment, make_catalog, make_enrollment, multipart, submit, wait_scanned

KEY_RE = re.compile(r"^tenants/default/requests/[0-9a-f-]{36}/[0-9a-f]{32}$")


@pytest.fixture
async def world(harness):
    """A student with a verified enrollment, a staff member, and the catalog."""
    cat = await make_catalog(harness)
    student, user = await harness.logged_in()
    admin, _ = await harness.logged_in(Role.ADMIN)
    enrollment = await make_enrollment(harness, user, cat)
    async with student, admin:
        yield harness, cat, student, admin, enrollment, user


async def _doc(h, doc_id) -> Document:
    async with h.app.state.sessionmaker() as db:
        return await db.get(Document, uuid.UUID(doc_id))


async def _audit(h, action: str, doc_id: str) -> list[AuditLog]:
    async with h.app.state.sessionmaker() as db:
        rows = await db.scalars(
            select(AuditLog).where(AuditLog.action == action, AuditLog.entity_id == doc_id)
        )
        return list(rows.all())


async def _create(world, content: bytes = PDF, name: str = "piece.pdf") -> dict:
    _, cat, student, _, enrollment, _ = world
    res = await submit(
        student,
        enrollment.id,
        [(cat.with_attachment, 1)],
        [attachment(cat.with_attachment, name=name, content=content)],
    )
    assert res.status_code == 201, res.text
    return res.json()


# --- the full path ----------------------------------------------------------------------------------


async def test_clean_file_goes_through_the_whole_pipeline(world):
    h, _, student, admin, _, _ = world
    req = await _create(world)
    [doc] = req["documents"]
    assert doc["scan_status"] == "SCANNING" and doc["can_download"] is False
    assert doc["sha256"] and doc["original_filename"] is None  # the raw name is for staff only

    # Not downloadable while SCANNING (409, and the refusal is audited)...
    early = await student.get(f"/api/v1/requests/{req['id']}/documents/{doc['id']}/download")
    # (the scan may already be over on a fast machine: then the file is served, never anything else)
    assert early.status_code in (200, 409)
    if early.status_code == 409:
        assert early.json()["error"]["code"] == "document_not_available"
        assert len(await _audit(h, "DOCUMENT_DOWNLOAD_REFUSED", doc["id"])) == 1

    # ...then the real worker scans it with ClamAV.
    detail = await wait_scanned(student, f"/api/v1/requests/{req['id']}")
    [doc] = detail["documents"]
    assert doc["scan_status"] == "CLEAN" and doc["can_download"] and doc["scanned_at"]
    res = await student.get(f"/api/v1/requests/{req['id']}/documents/{doc['id']}/download")
    assert res.status_code == 200 and res.content == PDF
    assert res.headers["content-length"] == str(len(PDF))
    assert res.headers["x-content-type-options"] == "nosniff"
    staff = await admin.get(f"/api/v1/admin/requests/{req['id']}/documents/{doc['id']}/download")
    assert staff.status_code == 200 and staff.content == PDF

    stored = await _doc(h, doc["id"])
    assert KEY_RE.match(stored.storage_key) and "piece" not in stored.storage_key
    assert stored.scan_attempts == 1 and stored.original_filename == "piece.pdf"
    [scanned] = await _audit(h, "DOCUMENT_SCANNED", doc["id"])
    assert scanned.details["result"] == "CLEAN"
    assert [a.details["sha256"] for a in await _audit(h, "DOCUMENT_UPLOADED", doc["id"])] == [stored.sha256]
    served = 2 + (early.status_code == 200)
    assert len(await _audit(h, "DOCUMENT_DOWNLOADED", doc["id"])) == served
    # Audit entries hold metadata only, never file content.
    for entry in await _audit(h, "DOCUMENT_UPLOADED", doc["id"]):
        assert "PDF" not in str(entry.details)


async def test_eicar_is_detected_quarantined_and_never_served(world):
    h, _, student, admin, _, user = world
    req = await _create(world, content=eicar_pdf(), name="attestation.pdf")
    detail = await wait_scanned(student, f"/api/v1/requests/{req['id']}")
    [doc] = detail["documents"]
    assert doc["scan_status"] == "INFECTED" and doc["can_download"] is False
    assert doc["scan_reason"] == "virus_detected"
    assert doc["scan_detail"] is None  # the signature name is for staff only

    staff_view = (await admin.get(f"/api/v1/admin/requests/{req['id']}")).json()["documents"][0]
    assert staff_view["scan_detail"].startswith("virus_detected:") and "Eicar" in staff_view["scan_detail"]

    for client, path in (
        (student, f"/api/v1/requests/{req['id']}/documents/{doc['id']}/download"),
        (admin, f"/api/v1/admin/requests/{req['id']}/documents/{doc['id']}/download"),
    ):
        res = await client.get(path)
        assert res.status_code == 409
        assert res.json()["error"]["details"] == {"scan_status": "INFECTED"}
    assert len(await _audit(h, "DOCUMENT_DOWNLOAD_REFUSED", doc["id"])) == 2

    # The object left the regular key space.
    stored = await _doc(h, doc["id"])
    storage = h.app.state.storage
    assert stored.storage_key.startswith("quarantine/tenants/") and stored.quarantined_at
    assert await storage.exists(stored.storage_key)
    assert not await storage.exists(stored.storage_key.removeprefix("quarantine/"))

    async with h.app.state.sessionmaker() as db:
        types = (await db.scalars(select(Notification.type).where(Notification.user_id == user.id))).all()
    assert "DOCUMENT_INFECTED" in types


async def test_issued_document_uses_the_same_pipeline(world):
    h, cat, student, admin, enrollment, _ = world
    req = (await submit(student, enrollment.id, [(cat.digital, 1)])).json()
    rid = req["id"]
    for status in ("IN_REVIEW", "PROCESSING", "APPROVED"):
        res = await admin.post(
            f"/api/v1/admin/requests/{rid}/transitions", json={"to_status": status}, headers=csrf(admin)
        )
        assert res.status_code == 200
    up = await admin.post(
        f"/api/v1/admin/requests/{rid}/documents",
        files=[("files", ("final.pdf", eicar_pdf(), "application/pdf"))],
        headers=csrf(admin),
    )
    assert up.status_code == 201 and up.json()[0]["scan_status"] == "SCANNING"
    infected_id = up.json()[0]["id"]
    detail = await wait_scanned(admin, f"/api/v1/admin/requests/{rid}")
    assert detail["documents"][0]["scan_status"] == "INFECTED"

    # An infected (or unscanned) final document can never be delivered.
    blocked = await admin.post(
        f"/api/v1/admin/requests/{rid}/transitions",
        json={"to_status": "DOCUMENT_AVAILABLE"},
        headers=csrf(admin),
    )
    assert blocked.json()["error"]["code"] == "issued_document_not_clean"

    # Replace it: delete (object removed, metadata + audit kept), upload a clean one.
    key = (await _doc(h, infected_id)).storage_key
    gone = await admin.delete(f"/api/v1/admin/requests/{rid}/documents/{infected_id}", headers=csrf(admin))
    assert gone.status_code == 204
    assert not await h.app.state.storage.exists(key)
    assert (await _doc(h, infected_id)).deleted_at is not None
    assert len(await _audit(h, "DOCUMENT_DELETED", infected_id)) == 1
    assert (await admin.get(f"/api/v1/admin/requests/{rid}")).json()["documents"] == []

    await admin.post(
        f"/api/v1/admin/requests/{rid}/documents",
        files=[("files", ("final.pdf", PDF, "application/pdf"))],
        headers=csrf(admin),
    )
    await wait_scanned(admin, f"/api/v1/admin/requests/{rid}")
    ok = await admin.post(
        f"/api/v1/admin/requests/{rid}/transitions",
        json={"to_status": "DOCUMENT_AVAILABLE"},
        headers=csrf(admin),
    )
    assert ok.json()["status"] == "DOCUMENT_AVAILABLE"
    [issued] = (await student.get("/api/v1/requests/documents")).json()
    assert issued["scan_status"] == "CLEAN" and issued["can_download"]


async def test_message_attachments_are_scanned_too(world):
    _, _, student, _, _, _ = world
    req = await _create(world)
    res = await student.post(
        f"/api/v1/requests/{req['id']}/messages",
        files=multipart([("files", ("cv.pdf", eicar_pdf(), "application/pdf"))], body="Voici le fichier"),
        headers=csrf(student),
    )
    assert res.status_code == 201
    assert res.json()["attachments"][0]["scan_status"] == "SCANNING"
    for _ in range(200):
        [message] = (await student.get(f"/api/v1/requests/{req['id']}/messages")).json()
        if message["attachments"][0]["scan_status"] != "SCANNING":
            break
        await asyncio.sleep(0.25)
    assert message["attachments"][0]["scan_status"] == "INFECTED"


# --- failure modes (scan driven directly; nothing consumes this app's queue) -----------------------


@pytest.fixture
async def idle_queue(make_settings, harness_for):
    """An app whose scans are queued on a queue no worker consumes: documents stay SCANNING."""
    queue = f"unconsumed-{uuid.uuid4().hex[:8]}"
    async for h in harness_for(make_settings(scan_queue=queue)):
        await h.ensure_domain()
        cat = await make_catalog(h)
        student, user = await h.logged_in()
        enrollment = await make_enrollment(h, user, cat)
        async with student:
            yield h, cat, student, enrollment
        await h.app.state.redis.delete(queue)


async def _pending_doc(idle_queue) -> tuple[dict, Document]:
    h, cat, student, enrollment = idle_queue
    res = await submit(student, enrollment.id, [(cat.with_attachment, 1)], [attachment(cat.with_attachment)])
    req = res.json()
    doc = await _doc(h, req["documents"][0]["id"])
    assert doc.scan_status == ScanStatus.SCANNING
    return req, doc


def _clamd(settings, **kw) -> ClamdScanner:
    return ClamdScanner(
        kw.get("host", settings.clamav_host), kw.get("port", settings.clamav_port), kw.get("timeout", 30)
    )


async def test_unscanned_document_is_never_served(idle_queue):
    h, _, student, _ = idle_queue
    req, doc = await _pending_doc(idle_queue)
    res = await student.get(f"/api/v1/requests/{req['id']}/documents/{doc.id}/download")
    assert res.status_code == 409 and res.json()["error"]["details"]["scan_status"] == "SCANNING"


async def test_scanner_outage_retries_then_fails_closed_and_can_be_rescanned(idle_queue, harness):
    h, _, student, _ = idle_queue
    req, doc = await _pending_doc(idle_queue)
    maker, storage, settings = h.app.state.sessionmaker, h.app.state.storage, h.app.state.settings
    down = _clamd(settings, port=1, timeout=2)

    # Transient: still SCANNING, attempt counted, the task will retry.
    assert await scan_document(maker, storage, down, doc.id, final_attempt=False) == ScanOutcome.RETRY
    assert (await _doc(h, str(doc.id))).scan_status == ScanStatus.SCANNING
    # Retries exhausted: ERROR, never CLEAN.
    assert await scan_document(maker, storage, down, doc.id, final_attempt=True) == ScanOutcome.ERROR
    failed = await _doc(h, str(doc.id))
    assert failed.scan_status == ScanStatus.ERROR and failed.scan_detail == "scanner_unavailable"
    assert failed.scan_attempts == 2
    res = await student.get(f"/api/v1/requests/{req['id']}/documents/{doc.id}/download")
    assert res.status_code == 409 and res.json()["error"]["details"]["scan_status"] == "ERROR"

    # Once ClamAV is back, staff can queue a new scan (here processed by the real test worker).
    admin, _ = await harness.logged_in(Role.ADMIN)
    async with admin:
        res = await admin.post(
            f"/api/v1/admin/requests/{req['id']}/documents/{doc.id}/rescan", headers=csrf(admin)
        )
        assert res.status_code == 200 and res.json()["scan_status"] == "SCANNING"
        again = await admin.post(
            f"/api/v1/admin/requests/{req['id']}/documents/{doc.id}/rescan", headers=csrf(admin)
        )
        assert again.status_code == 409 and again.json()["error"]["code"] == "rescan_not_allowed"
        detail = await wait_scanned(admin, f"/api/v1/admin/requests/{req['id']}")
    assert detail["documents"][0]["scan_status"] == "CLEAN"


async def test_scanner_timeout_is_an_outage():
    """A daemon that accepts the connection but never answers must not hang the worker."""
    server = socket.create_server(("127.0.0.1", 0))
    port = server.getsockname()[1]
    accepted = []
    threading.Thread(target=lambda: accepted.append(server.accept()), daemon=True).start()
    try:
        with pytest.raises(ScannerUnavailable):
            await asyncio.to_thread(ClamdScanner("127.0.0.1", port, timeout=1).scan, [PDF])
    finally:
        server.close()


async def test_missing_object_ends_in_error(idle_queue):
    h, _, _, _ = idle_queue
    _, doc = await _pending_doc(idle_queue)
    await h.app.state.storage.delete(doc.storage_key)
    outcome = await scan_document(
        h.app.state.sessionmaker,
        h.app.state.storage,
        _clamd(h.app.state.settings),
        doc.id,
        final_attempt=False,
    )
    assert outcome == ScanOutcome.ERROR
    assert (await _doc(h, str(doc.id))).scan_detail == "file_missing"


async def test_unexpected_scanner_failure_fails_closed(idle_queue):
    """Test double: a scanner raising an arbitrary exception (a bug, a library crash)."""

    class BrokenScanner:
        def scan(self, chunks):
            raise RuntimeError("boom")

        def ping(self):
            return True

    h, _, _, _ = idle_queue
    _, doc = await _pending_doc(idle_queue)
    outcome = await scan_document(
        h.app.state.sessionmaker, h.app.state.storage, BrokenScanner(), doc.id, final_attempt=False
    )
    assert outcome == ScanOutcome.ERROR
    assert (await _doc(h, str(doc.id))).scan_status == ScanStatus.ERROR


async def test_scan_is_idempotent_under_duplicates_and_concurrency(idle_queue):
    h, _, _, _ = idle_queue
    _, doc = await _pending_doc(idle_queue)
    maker, storage, settings = h.app.state.sessionmaker, h.app.state.storage, h.app.state.settings

    outcomes = await asyncio.gather(
        *(scan_document(maker, storage, _clamd(settings), doc.id, final_attempt=False) for _ in range(3))
    )
    assert sorted(outcomes) == sorted([ScanOutcome.CLEAN, ScanOutcome.SKIPPED, ScanOutcome.SKIPPED])
    # A late duplicate (task executed twice) changes nothing.
    assert (
        await scan_document(maker, storage, _clamd(settings), doc.id, final_attempt=False)
        == ScanOutcome.SKIPPED
    )
    stored = await _doc(h, str(doc.id))
    assert stored.scan_status == ScanStatus.CLEAN and stored.scan_attempts == 1
    assert len(await _audit(h, "DOCUMENT_SCANNED", str(doc.id))) == 1

    # Same through the real Celery task.
    result = scan_document_task.apply_async(args=[str(doc.id)], queue=settings_queue())
    assert await asyncio.to_thread(result.get, timeout=30) == "SKIPPED"
    assert len(await _audit(h, "DOCUMENT_SCANNED", str(doc.id))) == 1


def settings_queue() -> str:
    from app.worker.context import worker_context

    return worker_context().settings.scan_queue


async def test_restarted_worker_picks_up_pending_scans(idle_queue):
    """Message lost (or worker restarted): the startup sweep re-queues every SCANNING document."""
    h, _, student, _ = idle_queue
    req, doc = await _pending_doc(idle_queue)
    assert await asyncio.to_thread(enqueue_pending_scans) >= 1
    detail = await wait_scanned(student, f"/api/v1/requests/{req['id']}")
    assert detail["documents"][0]["scan_status"] == "CLEAN"


# --- access control ---------------------------------------------------------------------------------


async def test_download_access_rules(world, harness):
    h, _, student, admin, _, _ = world
    req = await _create(world)
    await wait_scanned(student, f"/api/v1/requests/{req['id']}")
    doc_id = req["documents"][0]["id"]
    own = f"/api/v1/requests/{req['id']}/documents/{doc_id}/download"
    staff = f"/api/v1/admin/requests/{req['id']}/documents/{doc_id}/download"

    async with h.client() as anonymous:
        assert (await anonymous.get(own)).status_code == 401
        assert (await anonymous.get(staff)).status_code == 401
    other, _ = await harness.logged_in()
    async with other:
        assert (await other.get(own)).status_code == 404  # another student: not found
        assert (await other.get(staff)).status_code == 403  # not staff
    assert (await student.get(staff)).status_code == 403

    # Staff without `requests.read` is refused (RBAC is data: remove it, then restore it).
    async with await h.db() as db:
        await db.execute(
            delete(RolePermission).where(
                RolePermission.role == Role.ADMIN, RolePermission.permission_code == "requests.read"
            )
        )
        await db.commit()
    try:
        assert (await admin.get(staff)).status_code == 403
    finally:
        async with await h.db() as db:
            await db.execute(insert(RolePermission).values(role=Role.ADMIN, permission_code="requests.read"))
            await db.commit()
    assert (await admin.get(staff)).status_code == 200


async def test_storage_is_private_and_keys_are_never_exposed(world):
    h, _, student, admin, _, _ = world
    req = await _create(world)
    await wait_scanned(student, f"/api/v1/requests/{req['id']}")
    key = (await _doc(h, req["documents"][0]["id"])).storage_key

    # Direct anonymous access to the S3 endpoint is refused (object and bucket listing).
    settings = h.app.state.settings
    async with httpx.AsyncClient(base_url=settings.s3_endpoint_url, timeout=5) as s3:
        assert (await s3.get(f"/{settings.s3_bucket}/{key}")).status_code in (401, 403)
        assert (await s3.get(f"/{settings.s3_bucket}")).status_code in (401, 403)

    responses = [
        await student.get(f"/api/v1/requests/{req['id']}"),
        await student.get("/api/v1/requests"),
        await student.get("/api/v1/requests/documents"),
        await student.get(f"/api/v1/requests/{req['id']}/messages"),
        await admin.get(f"/api/v1/admin/requests/{req['id']}"),
        await admin.get("/api/v1/admin/requests"),
    ]
    for res in responses:
        assert res.status_code == 200
        assert key not in res.text and "storage_key" not in res.text and "tenants/" not in res.text


async def test_identical_files_are_kept_and_detectable(world):
    h, *_ = world
    first = await _create(world)
    second = await _create(world)
    a = await _doc(h, first["documents"][0]["id"])
    b = await _doc(h, second["documents"][0]["id"])
    assert a.sha256 == b.sha256 and a.storage_key != b.storage_key
    async with h.app.state.sessionmaker() as db:
        same = await db.scalar(select(func.count()).select_from(Document).where(Document.sha256 == a.sha256))
    assert same >= 2  # duplicates are reported by hash, never deleted automatically


@pytest.mark.parametrize(
    ("name", "content", "declared", "code"),
    [
        ("document.pdf", b"MZ\x90\x00" + b"\x00" * 64, "application/pdf", "file_type_not_allowed"),
        ("scan.png", PDF, "image/png", "file_extension_mismatch"),
        ("piece.pdf", PDF, "image/png", "file_mime_mismatch"),
        ("facture.exe.pdf", PDF, "application/pdf", "file_name_not_allowed"),
    ],
)
async def test_falsified_uploads_are_refused_before_storage(world, name, content, declared, code):
    h, cat, student, _, enrollment, _ = world
    async with h.app.state.sessionmaker() as db:
        before = await db.scalar(select(func.count()).select_from(Document))
    res = await submit(
        student,
        enrollment.id,
        [(cat.with_attachment, 1)],
        [(f"attachment:{cat.with_attachment.id}", (name, content, declared))],
    )
    assert res.status_code == 422 and res.json()["error"]["code"] == code
    async with h.app.state.sessionmaker() as db:
        assert await db.scalar(select(func.count()).select_from(Document)) == before


async def test_oversized_upload_is_refused(make_settings, harness_for):
    async for h in harness_for(make_settings(max_upload_bytes=1024)):
        await h.ensure_domain()
        cat = await make_catalog(h)
        student, user = await h.logged_in()
        enrollment = await make_enrollment(h, user, cat)
        async with student:
            res = await submit(
                student,
                enrollment.id,
                [(cat.with_attachment, 1)],
                [attachment(cat.with_attachment, content=PDF + b"0" * 2048)],
            )
    assert res.status_code == 422 and res.json()["error"]["code"] == "file_too_large"


def test_worker_process_maps_every_model_on_its_own():
    """The worker imports no router: it must still configure every mapper (regression, found by E2E)."""
    import subprocess
    import sys

    code = (
        "import app.worker.tasks\n"
        "from sqlalchemy.orm import configure_mappers\n"
        "configure_mappers()\n"
        "from app.documents.models import Document\n"
        "assert Document.__table__.c.message_id.foreign_keys\n"
    )
    result = subprocess.run(  # noqa: S603 - fixed code, current interpreter
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False
    )
    assert result.returncode == 0, result.stderr[-2000:]
