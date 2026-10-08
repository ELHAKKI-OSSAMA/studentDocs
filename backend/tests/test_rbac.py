"""Authorization: permissions per role, admin isolation, ownership between students."""

import uuid

import pytest

from app.users.models import Role
from tests.conftest import PASSWORD, csrf

ADMIN_READ_ENDPOINTS = [
    "/api/v1/admin/dashboard",
    "/api/v1/admin/users",
    "/api/v1/admin/students",
    "/api/v1/admin/catalog/academic-years",
    "/api/v1/admin/catalog/branch-categories",
    "/api/v1/admin/catalog/branches",
    "/api/v1/admin/catalog/study-levels",
    "/api/v1/admin/catalog/document-types",
]

SUPER_ADMIN_WRITES = [
    ("post", "/api/v1/admin/catalog/branch-categories", {"code": "X", "name_i18n": {"fr": "X"}}),
    (
        "post",
        "/api/v1/admin/catalog/academic-years",
        {"label": "2090-2091", "start_date": "2090-09-01", "end_date": "2091-07-31"},
    ),
    (
        "post",
        "/api/v1/admin/users",
        {"email": "n@x.ma", "first_name": "N", "last_name": "X", "role": "ADMIN", "password": "Abcdefgh1234"},
    ),
    ("post", "/api/v1/admin/settings/email-domains", {"domain": "evil.ma"}),
]


async def test_unauthenticated_requests_are_rejected(client):
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    assert (await client.get("/api/v1/catalog/branches")).status_code == 401
    for path in ADMIN_READ_ENDPOINTS:
        res = await client.get(path)
        assert res.status_code == 401, path
        assert res.json()["error"]["code"] == "not_authenticated"


async def test_student_can_use_student_endpoints_but_not_admin(harness):
    client, _ = await harness.logged_in(Role.STUDENT)
    async with client:
        assert (await client.get("/api/v1/catalog/academic-years")).status_code == 200
        assert (await client.get("/api/v1/students/me/enrollments")).status_code == 200
        for path in ADMIN_READ_ENDPOINTS:
            res = await client.get(path)
            assert res.status_code == 403, path
            assert res.json()["error"]["code"] == "forbidden"
        for method, path, body in SUPER_ADMIN_WRITES:
            res = await getattr(client, method)(path, json=body, headers=csrf(client))
            assert res.status_code == 403, path


async def test_admin_can_read_admin_area_but_not_use_super_admin_permissions(harness):
    client, _ = await harness.logged_in(Role.ADMIN)
    async with client:
        me = (await client.get("/api/v1/auth/me")).json()
        assert "admin.access" in me["permissions"] and "catalog.manage" not in me["permissions"]
        for path in ADMIN_READ_ENDPOINTS:
            assert (await client.get(path)).status_code == 200, path
        for method, path, body in SUPER_ADMIN_WRITES:
            res = await getattr(client, method)(path, json=body, headers=csrf(client))
            assert res.status_code == 403, path
        assert (await client.get("/api/v1/admin/settings/email-domains")).status_code == 403
        # Admins have no student self-service permissions either.
        assert (await client.get("/api/v1/students/me/enrollments")).status_code == 403


async def test_super_admin_has_full_access(harness):
    client, _ = await harness.logged_in(Role.SUPER_ADMIN)
    async with client:
        for path in [*ADMIN_READ_ENDPOINTS, "/api/v1/admin/settings/email-domains"]:
            assert (await client.get(path)).status_code == 200, path


async def _enrollment_refs(harness) -> dict:
    """Creates a category / branch / level / active year as super-admin and returns their ids."""
    admin, _ = await harness.logged_in(Role.SUPER_ADMIN)
    tag = uuid.uuid4().hex[:6].upper()
    async with admin:
        h = csrf(admin)
        cat = (
            await admin.post(
                "/api/v1/admin/catalog/branch-categories",
                json={"code": f"C{tag}", "name_i18n": {"fr": "Cat"}},
                headers=h,
            )
        ).json()
        branch = (
            await admin.post(
                "/api/v1/admin/catalog/branches",
                json={"category_id": cat["id"], "code": "B1", "name_i18n": {"fr": "Br"}},
                headers=h,
            )
        ).json()
        level = (
            await admin.post(
                "/api/v1/admin/catalog/study-levels",
                json={"category_id": cat["id"], "code": "Y1", "name_i18n": {"fr": "Y1"}},
                headers=h,
            )
        ).json()
        first = 3000 + int(tag[:4], 16) % 5000
        year = (
            await admin.post(
                "/api/v1/admin/catalog/academic-years",
                json={
                    "label": f"{first}-{first + 1}",
                    "start_date": f"{first}-09-01",
                    "end_date": f"{first + 1}-07-31",
                },
                headers=h,
            )
        ).json()
    return {"academic_year_id": year["id"], "branch_id": branch["id"], "study_level_id": level["id"]}


async def test_student_cannot_access_another_students_resources(harness):
    refs = await _enrollment_refs(harness)
    alice, _ = await harness.logged_in()
    bob, _ = await harness.logged_in()
    async with alice, bob:
        res = await alice.post("/api/v1/students/me/enrollments", json=refs, headers=csrf(alice))
        assert res.status_code == 201, res.text
        alice_enrollment = res.json()["id"]

        # Bob sees only his own (empty) list and cannot delete Alice's enrollment — it "does not exist".
        assert (await bob.get("/api/v1/students/me/enrollments")).json() == []
        res = await bob.delete(f"/api/v1/students/me/enrollments/{alice_enrollment}", headers=csrf(bob))
        assert res.status_code == 404

        mine = (await alice.get("/api/v1/students/me/enrollments")).json()
        assert [e["id"] for e in mine] == [alice_enrollment]
        # Duplicate enrollment for the same year/branch → 409.
        dup = await alice.post("/api/v1/students/me/enrollments", json=refs, headers=csrf(alice))
        assert dup.status_code == 409
        res = await alice.delete(f"/api/v1/students/me/enrollments/{alice_enrollment}", headers=csrf(alice))
        assert res.status_code == 204


async def test_role_change_revokes_sessions_and_applies_new_permissions(harness):
    super_client, _ = await harness.logged_in(Role.SUPER_ADMIN)
    admin_client, admin = await harness.logged_in(Role.ADMIN)
    async with super_client, admin_client:
        res = await super_client.patch(
            f"/api/v1/admin/users/{admin.id}", json={"role": "SUPER_ADMIN"}, headers=csrf(super_client)
        )
        assert res.status_code == 200 and res.json()["role"] == "SUPER_ADMIN"
        # Old session dropped; a fresh login carries the new permissions.
        assert (await admin_client.get("/api/v1/auth/me")).status_code == 401
        res = await admin_client.post("/api/v1/auth/login", json={"email": admin.email, "password": PASSWORD})
        assert "catalog.manage" in res.json()["permissions"]


async def test_user_management_guards(harness):
    super_client, super_user = await harness.logged_in(Role.SUPER_ADMIN)
    student = await harness.create_user(Role.STUDENT)
    async with super_client:
        h = csrf(super_client)
        self_edit = await super_client.patch(
            f"/api/v1/admin/users/{super_user.id}", json={"is_active": False}, headers=h
        )
        assert self_edit.json()["error"]["code"] == "cannot_modify_self"
        promote = await super_client.patch(
            f"/api/v1/admin/users/{student.id}", json={"role": "ADMIN"}, headers=h
        )
        assert promote.json()["error"]["code"] == "invalid_role_change"
        bad_role = await super_client.post(
            "/api/v1/admin/users",
            json={
                "email": f"s{uuid.uuid4().hex[:6]}@x.ma",
                "first_name": "A",
                "last_name": "B",
                "role": "STUDENT",
                "password": "Abcdefgh1234",
            },
            headers=h,
        )
        assert bad_role.status_code == 422

        email = f"staff-{uuid.uuid4().hex[:6]}@univ.ma"
        created = await super_client.post(
            "/api/v1/admin/users",
            json={
                "email": email,
                "first_name": "New",
                "last_name": "Admin",
                "role": "ADMIN",
                "password": "Abcdefgh1234",
            },
            headers=h,
        )
        assert created.status_code == 201 and created.json()["email_verified"] is True
        dup = await super_client.post(
            "/api/v1/admin/users",
            json={
                "email": email,
                "first_name": "New",
                "last_name": "Admin",
                "role": "ADMIN",
                "password": "Abcdefgh1234",
            },
            headers=h,
        )
        assert dup.status_code == 409
    async with harness.client() as new_admin:
        res = await new_admin.post("/api/v1/auth/login", json={"email": email, "password": "Abcdefgh1234"})
        assert res.status_code == 200 and res.json()["role"] == "ADMIN"


@pytest.mark.parametrize("payload", [{"domain": "not a domain"}, {"domain": "a"}])
async def test_email_domain_validation(harness, payload):
    client, _ = await harness.logged_in(Role.SUPER_ADMIN)
    async with client:
        res = await client.post("/api/v1/admin/settings/email-domains", json=payload, headers=csrf(client))
        assert res.status_code == 422
