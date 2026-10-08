from sqlalchemy import func, select

from app.academic.models import AcademicYear, Branch, BranchCategory, DocumentType, StudyLevel
from app.scripts.seed import BRANCHES, CATEGORIES, DOCUMENT_TYPES, YEARS, seed
from app.users.models import User
from tests.conftest import PASSWORD


async def _count(db, model, *where) -> int:
    return await db.scalar(select(func.count()).select_from(model).where(*where))


async def test_seed_is_idempotent_and_creates_working_accounts(harness):
    async with await harness.db() as db:
        for _ in range(2):  # running twice must not duplicate anything
            await seed(db, student_domain="seed-univ.ma", demo_password=PASSWORD)

        codes = [c for c, _, _ in CATEGORIES]
        assert await _count(db, BranchCategory, BranchCategory.code.in_(codes)) == len(CATEGORIES)
        assert await _count(db, AcademicYear, AcademicYear.label.in_([y[0] for y in YEARS])) == len(YEARS)
        assert await _count(db, DocumentType, DocumentType.code.in_([d[0] for d in DOCUMENT_TYPES])) == len(
            DOCUMENT_TYPES
        )
        seeded_branches = await _count(
            db,
            Branch,
            Branch.category_id.in_(select(BranchCategory.id).where(BranchCategory.code.in_(codes))),
        )
        assert seeded_branches == sum(len(v) for v in BRANCHES.values())
        assert await _count(db, StudyLevel) >= 9
        assert await _count(db, User, User.email == "etudiant@seed-univ.ma") == 1

    async with harness.client() as client:
        for email, role in (
            ("superadmin@univ-demo.ma", "SUPER_ADMIN"),
            ("admin@univ-demo.ma", "ADMIN"),
            ("etudiant@seed-univ.ma", "STUDENT"),
        ):
            res = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
            assert res.status_code == 200, (email, res.text)
            assert res.json()["role"] == role
        enrollments = (await client.get("/api/v1/students/me/enrollments")).json()
        assert enrollments[0]["branch"]["code"] == "IA"
