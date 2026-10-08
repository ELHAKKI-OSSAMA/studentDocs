"""Test data builders writing real rows in the test database."""

import json
import random
import uuid
from dataclasses import dataclass
from datetime import date

from httpx import AsyncClient
from sqlalchemy import select

from app.academic.models import AcademicYear, Branch, BranchCategory, DeliveryMode, DocumentType, StudyLevel
from app.students.models import EnrollmentSource, EnrollmentStatus, Student, StudentEnrollment
from app.users.models import User
from tests.conftest import Harness, csrf

PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
EXE = b"MZ\x90\x00" + b"\x00" * 64


@dataclass
class Catalog:
    category: BranchCategory
    other_category: BranchCategory
    branch: Branch
    level: StudyLevel
    year: AcademicYear
    digital: DocumentType  # no attachment needed
    with_attachment: DocumentType  # digital, attachment required
    pickup: DocumentType  # physical pickup
    other_category_only: DocumentType  # restricted to other_category


async def make_catalog(h: Harness) -> Catalog:
    tag = uuid.uuid4().hex[:8].upper()
    first = random.randint(3000, 9000)  # noqa: S311
    async with h.app.state.sessionmaker() as db:
        cat = BranchCategory(code=f"C{tag}", name_i18n={"fr": "Master"}, sort_order=1, is_active=True)
        other = BranchCategory(code=f"O{tag}", name_i18n={"fr": "Licence"}, sort_order=2, is_active=True)
        db.add_all([cat, other])
        await db.flush()
        branch = Branch(category_id=cat.id, code="IA", name_i18n={"fr": "IA"}, is_active=True)
        level = StudyLevel(
            category_id=cat.id, code="M1", name_i18n={"fr": "M1"}, sort_order=1, is_active=True
        )
        year = AcademicYear(
            label=f"{first}-{first + 1}", start_date=date(first, 9, 1), end_date=date(first + 1, 7, 31)
        )

        def doc(code: str, **kw) -> DocumentType:
            values = {
                "delivery_mode": DeliveryMode.DIGITAL,
                "requires_attachment": False,
                "max_quantity": 3,
                "processing_days": 2,
                "is_active": True,
            } | kw
            return DocumentType(code=f"{code}_{tag}", name_i18n={"fr": code}, **values)

        digital = doc("ATTESTATION")
        with_attachment = doc("CONVENTION", requires_attachment=True, max_quantity=1)
        pickup = doc("DIPLOME", delivery_mode=DeliveryMode.PICKUP, max_quantity=1)
        restricted = doc("FORMATION")
        restricted.allowed_categories = [other]
        db.add_all([branch, level, year, digital, with_attachment, pickup, restricted])
        await db.commit()
        return Catalog(cat, other, branch, level, year, digital, with_attachment, pickup, restricted)


async def student_of(h: Harness, user: User) -> Student:
    async with h.app.state.sessionmaker() as db:
        return await db.scalar(select(Student).where(Student.user_id == user.id))


async def make_enrollment(
    h: Harness, user: User, catalog: Catalog, status: EnrollmentStatus = EnrollmentStatus.VERIFIED
) -> StudentEnrollment:
    student = await student_of(h, user)
    async with h.app.state.sessionmaker() as db:
        enrollment = StudentEnrollment(
            student_id=student.id,
            academic_year_id=catalog.year.id,
            branch_id=catalog.branch.id,
            study_level_id=catalog.level.id,
            status=status,
            source=EnrollmentSource.ADMIN,
        )
        db.add(enrollment)
        await db.commit()
        return enrollment


def multipart(files: list | None = None, **fields: str) -> list:
    """Always a real multipart/form-data body (like a browser FormData), even without files."""
    return [(name, (None, value)) for name, value in fields.items()] + list(files or [])


async def submit(
    client: AsyncClient,
    enrollment_id,
    items: list[tuple[DocumentType, int]],
    files: list[tuple[str, tuple[str, bytes, str]]] | None = None,
    **extra,
):
    payload = {
        "enrollment_id": str(enrollment_id),
        "items": [{"document_type_id": str(t.id), "quantity": q} for t, q in items],
    } | extra
    return await client.post(
        "/api/v1/requests", files=multipart(files, payload=json.dumps(payload)), headers=csrf(client)
    )


def attachment(
    doc_type: DocumentType, name: str = "piece.pdf", content: bytes = PDF, mime: str = "application/pdf"
):
    return (f"attachment:{doc_type.id}", (name, content, mime))


async def transition(client: AsyncClient, request_id, to_status: str, comment: str | None = None):
    return await client.post(
        f"/api/v1/admin/requests/{request_id}/transitions",
        json={"to_status": to_status, "comment": comment},
        headers=csrf(client),
    )
