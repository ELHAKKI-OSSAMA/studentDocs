"""Enrollment declaration (student) and verification (administration)."""

from app.users.models import Role
from tests.conftest import csrf
from tests.factories import make_catalog, submit


async def test_declare_verify_and_use_an_enrollment(harness):
    cat = await make_catalog(harness)
    student, user = await harness.logged_in()
    admin, _ = await harness.logged_in(Role.ADMIN)
    async with student, admin:
        body = {
            "academic_year_id": str(cat.year.id),
            "branch_id": str(cat.branch.id),
            "study_level_id": str(cat.level.id),
        }
        declared = (
            await student.post("/api/v1/students/me/enrollments", json=body, headers=csrf(student))
        ).json()
        assert declared["status"] == "PENDING" and declared["source"] == "SELF_DECLARED"

        # Not usable yet.
        res = await submit(student, declared["id"], [(cat.digital, 1)])
        assert res.json()["error"]["code"] == "enrollment_not_verified"

        queue = (
            await admin.get("/api/v1/admin/enrollments", params={"status": "PENDING", "q": user.email})
        ).json()
        assert [e["id"] for e in queue["items"]] == [declared["id"]]
        assert queue["items"][0]["student_email"] == user.email

        reject = await admin.patch(
            f"/api/v1/admin/enrollments/{declared['id']}", json={"status": "REJECTED"}, headers=csrf(admin)
        )
        assert reject.status_code == 422 and reject.json()["error"]["code"] == "message_required"

        verified = await admin.patch(
            f"/api/v1/admin/enrollments/{declared['id']}",
            json={"status": "VERIFIED", "review_note": "Vérifié sur Apogée"},
            headers=csrf(admin),
        )
        assert verified.status_code == 200 and verified.json()["status"] == "VERIFIED"
        assert verified.json()["reviewed_at"] and verified.json()["reviewer_name"]
        assert queue["items"][0]["reviewer_name"] is None

        assert (await submit(student, declared["id"], [(cat.digital, 1)])).status_code == 201
        # A verified enrollment can no longer be removed by the student.
        res = await student.delete(f"/api/v1/students/me/enrollments/{declared['id']}", headers=csrf(student))
        assert res.status_code == 409 and res.json()["error"]["code"] == "enrollment_verified"


async def test_admin_can_correct_and_rejects_inconsistent_corrections(harness):
    cat = await make_catalog(harness)
    student, _ = await harness.logged_in()
    admin, _ = await harness.logged_in(Role.ADMIN)
    async with student, admin:
        body = {
            "academic_year_id": str(cat.year.id),
            "branch_id": str(cat.branch.id),
            "study_level_id": str(cat.level.id),
        }
        declared = (
            await student.post("/api/v1/students/me/enrollments", json=body, headers=csrf(student))
        ).json()

        # A level from another category is refused.
        superadmin, _ = await harness.logged_in(Role.SUPER_ADMIN)
        async with superadmin:
            other_level = (
                await superadmin.post(
                    "/api/v1/admin/catalog/study-levels",
                    json={"category_id": str(cat.other_category.id), "code": "L1", "name_i18n": {"fr": "L1"}},
                    headers=csrf(superadmin),
                )
            ).json()
            same_cat_level = (
                await superadmin.post(
                    "/api/v1/admin/catalog/study-levels",
                    json={"category_id": str(cat.category.id), "code": "M2", "name_i18n": {"fr": "M2"}},
                    headers=csrf(superadmin),
                )
            ).json()
        bad = await admin.patch(
            f"/api/v1/admin/enrollments/{declared['id']}",
            json={"status": "VERIFIED", "study_level_id": other_level["id"]},
            headers=csrf(admin),
        )
        assert bad.json()["error"]["code"] == "level_branch_mismatch"

        fixed = await admin.patch(
            f"/api/v1/admin/enrollments/{declared['id']}",
            json={"status": "VERIFIED", "study_level_id": same_cat_level["id"]},
            headers=csrf(admin),
        )
        assert fixed.json()["study_level"]["code"] == "M2" and fixed.json()["status"] == "VERIFIED"
        mine = (await student.get("/api/v1/students/me/enrollments")).json()
        assert mine[0]["study_level"]["code"] == "M2"


async def test_students_cannot_review_enrollments(harness):
    student, _ = await harness.logged_in()
    async with student:
        assert (await student.get("/api/v1/admin/enrollments")).status_code == 403
        res = await student.patch(
            "/api/v1/admin/enrollments/00000000-0000-0000-0000-000000000000",
            json={"status": "VERIFIED"},
            headers=csrf(student),
        )
        assert res.status_code == 403
