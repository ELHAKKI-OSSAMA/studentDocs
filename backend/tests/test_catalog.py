"""Catalog CRUD through the admin API (real PostgreSQL) + public catalog filtering rules."""

import uuid

import pytest

from app.users.models import Role
from tests.conftest import csrf

ADMIN = "/api/v1/admin/catalog"


@pytest.fixture
async def admin(harness):
    client, _ = await harness.logged_in(Role.SUPER_ADMIN)
    async with client:
        yield client


def _tag() -> str:
    return uuid.uuid4().hex[:8].upper()


async def _create(client, path, body, expected=201):
    res = await client.post(f"{ADMIN}{path}", json=body, headers=csrf(client))
    assert res.status_code == expected, res.text
    return res.json()


async def test_academic_year_crud_and_rules(admin):
    first = 4000 + int(_tag()[:4], 16) % 5000
    label = f"{first}-{first + 1}"
    body = {"label": label, "start_date": f"{first}-09-01", "end_date": f"{first + 1}-07-31"}
    year = await _create(admin, "/academic-years", body)
    assert year["status"] == "ACTIVE"

    await _create(admin, "/academic-years", body, expected=409)  # duplicate label
    bad = {"label": f"{first}-{first + 2}", "start_date": f"{first}-09-01", "end_date": f"{first + 2}-07-31"}
    await _create(admin, "/academic-years", bad, expected=422)  # not consecutive
    inverted = {
        "label": f"{first + 1}-{first + 2}",
        "start_date": f"{first + 2}-09-01",
        "end_date": f"{first + 1}-07-31",
    }
    await _create(admin, "/academic-years", inverted, expected=422)

    res = await admin.patch(
        f"{ADMIN}/academic-years/{year['id']}", json={"status": "ARCHIVED"}, headers=csrf(admin)
    )
    assert res.status_code == 200 and res.json()["status"] == "ARCHIVED"
    # Archived years disappear from the public catalog but stay in the admin list.
    public = (await admin.get("/api/v1/catalog/academic-years")).json()
    assert label not in [y["label"] for y in public]
    assert label in [y["label"] for y in (await admin.get(f"{ADMIN}/academic-years")).json()]

    assert (
        await admin.delete(f"{ADMIN}/academic-years/{year['id']}", headers=csrf(admin))
    ).status_code == 204
    assert (await admin.get(f"{ADMIN}/academic-years/{year['id']}")).status_code == 404


async def test_category_branch_level_hierarchy(admin):
    tag = _tag()
    cat = await _create(
        admin,
        "/branch-categories",
        {"code": f"cat_{tag}", "name_i18n": {"fr": "Master", "en": "Master", "ar": "ماستر"}},
    )
    assert cat["code"] == f"CAT_{tag}"  # codes are normalized

    branch = await _create(
        admin, "/branches", {"category_id": cat["id"], "code": "IA", "name_i18n": {"fr": "IA"}}
    )
    assert branch["category"]["id"] == cat["id"]
    await _create(
        admin, "/branches", {"category_id": cat["id"], "code": "IA", "name_i18n": {"fr": "x"}}, expected=409
    )
    await _create(
        admin,
        "/branches",
        {"category_id": str(uuid.uuid4()), "code": "Z", "name_i18n": {"fr": "x"}},
        expected=422,
    )
    level = await _create(
        admin,
        "/study-levels",
        {"category_id": cat["id"], "code": "M1", "name_i18n": {"fr": "M1"}, "sort_order": 1},
    )

    filtered = (await admin.get(f"{ADMIN}/branches", params={"category_id": cat["id"]})).json()
    assert [b["id"] for b in filtered] == [branch["id"]]

    res = await admin.patch(
        f"{ADMIN}/branches/{branch['id']}",
        json={"name_i18n": {"fr": "Intelligence artificielle"}},
        headers=csrf(admin),
    )
    assert res.status_code == 200 and res.json()["name_i18n"]["fr"] == "Intelligence artificielle"

    # A category with branches cannot be deleted (RESTRICT) → 409 "in_use".
    res = await admin.delete(f"{ADMIN}/branch-categories/{cat['id']}", headers=csrf(admin))
    assert res.status_code == 409 and res.json()["error"]["code"] == "in_use"

    # Deactivated branch: hidden from the public catalog.
    await admin.patch(f"{ADMIN}/branches/{branch['id']}", json={"is_active": False}, headers=csrf(admin))
    public = (await admin.get("/api/v1/catalog/branches", params={"category_id": cat["id"]})).json()
    assert public == []

    for path, obj in (("/branches", branch), ("/study-levels", level), ("/branch-categories", cat)):
        assert (await admin.delete(f"{ADMIN}{path}/{obj['id']}", headers=csrf(admin))).status_code == 204


async def test_document_type_rules_and_category_filter(admin, harness):
    tag = _tag()
    licence = await _create(admin, "/branch-categories", {"code": f"L_{tag}", "name_i18n": {"fr": "Licence"}})
    master = await _create(admin, "/branch-categories", {"code": f"M_{tag}", "name_i18n": {"fr": "Master"}})

    everyone = await _create(
        admin, "/document-types", {"code": f"ALL_{tag}", "name_i18n": {"fr": "Attestation"}}
    )
    master_only = await _create(
        admin,
        "/document-types",
        {
            "code": f"MASTER_{tag}",
            "name_i18n": {"fr": "Convention"},
            "delivery_mode": "PICKUP",
            "requires_attachment": True,
            "max_quantity": 3,
            "processing_days": 7,
            "allowed_category_ids": [master["id"]],
        },
    )
    assert [c["id"] for c in master_only["allowed_categories"]] == [master["id"]]
    await _create(
        admin,
        "/document-types",
        {"code": f"Q_{tag}", "name_i18n": {"fr": "x"}, "max_quantity": 11},
        expected=422,
    )
    await _create(
        admin,
        "/document-types",
        {"code": f"R_{tag}", "name_i18n": {"fr": "x"}, "allowed_category_ids": [str(uuid.uuid4())]},
        expected=422,
    )

    student, _ = await harness.logged_in(Role.STUDENT)
    async with student:

        def codes(res):
            return {d["code"] for d in res.json()}

        for_licence = codes(
            await student.get("/api/v1/catalog/document-types", params={"category_id": licence["id"]})
        )
        for_master = codes(
            await student.get("/api/v1/catalog/document-types", params={"category_id": master["id"]})
        )
        assert everyone["code"] in for_licence and master_only["code"] not in for_licence
        assert {everyone["code"], master_only["code"]} <= for_master

        # Rules are editable; clearing restrictions makes the type available to all categories.
        res = await admin.patch(
            f"{ADMIN}/document-types/{master_only['id']}",
            json={"allowed_category_ids": [], "is_active": False},
            headers=csrf(admin),
        )
        assert res.status_code == 200 and res.json()["allowed_categories"] == []
        all_types = codes(await student.get("/api/v1/catalog/document-types"))
        assert master_only["code"] not in all_types  # inactive → hidden from students


async def test_i18n_labels_are_validated(admin):
    await _create(
        admin, "/branch-categories", {"code": f"X_{_tag()}", "name_i18n": {"en": "missing fr"}}, expected=422
    )
    await _create(
        admin, "/branch-categories", {"code": f"X_{_tag()}", "name_i18n": {"fr": "<b>x</b>"}}, expected=422
    )
    await _create(admin, "/branch-categories", {"code": "bad code!", "name_i18n": {"fr": "x"}}, expected=422)


async def test_enrollment_requires_consistent_catalog(admin, harness):
    tag = _tag()
    cat_a = await _create(admin, "/branch-categories", {"code": f"A_{tag}", "name_i18n": {"fr": "A"}})
    cat_b = await _create(admin, "/branch-categories", {"code": f"B_{tag}", "name_i18n": {"fr": "B"}})
    branch = await _create(
        admin, "/branches", {"category_id": cat_a["id"], "code": "X", "name_i18n": {"fr": "X"}}
    )
    level_b = await _create(
        admin, "/study-levels", {"category_id": cat_b["id"], "code": "Y", "name_i18n": {"fr": "Y"}}
    )
    first = 5000 + int(tag[:4], 16) % 4000
    year = await _create(
        admin,
        "/academic-years",
        {
            "label": f"{first}-{first + 1}",
            "start_date": f"{first}-09-01",
            "end_date": f"{first + 1}-07-31",
            "status": "ARCHIVED",
        },
    )
    student, _ = await harness.logged_in()
    async with student:
        body = {"academic_year_id": year["id"], "branch_id": branch["id"], "study_level_id": level_b["id"]}
        res = await student.post("/api/v1/students/me/enrollments", json=body, headers=csrf(student))
        assert res.status_code == 422  # archived year
        await admin.patch(
            f"{ADMIN}/academic-years/{year['id']}", json={"status": "ACTIVE"}, headers=csrf(admin)
        )
        res = await student.post("/api/v1/students/me/enrollments", json=body, headers=csrf(student))
        assert res.status_code == 422 and res.json()["error"]["code"] == "level_branch_mismatch"
