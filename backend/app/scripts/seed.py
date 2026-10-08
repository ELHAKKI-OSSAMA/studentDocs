"""Idempotent development seed: catalog, allowed domain and (optionally) demo accounts.

Usage: python -m app.scripts.seed
Demo accounts are created only when SEED_DEMO_PASSWORD is set. Refuses to run in production.
"""

import asyncio
import logging
import os
import sys
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.academic.models import (
    AcademicYear,
    AcademicYearStatus,
    Branch,
    BranchCategory,
    DeliveryMode,
    DocumentType,
    StudyLevel,
)
from app.core.config import get_settings
from app.core.db import create_engine, create_sessionmaker
from app.core.logging import configure_logging
from app.core.security import hash_password
from app.students.models import EnrollmentSource, EnrollmentStatus, Student, StudentEnrollment
from app.users.models import AllowedEmailDomain, AuthIdentity, IdentityProvider, Role, User

logger = logging.getLogger("seed")


def t(fr: str, en: str, ar: str) -> dict:
    return {"fr": fr, "en": en, "ar": ar}


YEARS = [
    ("2024-2025", date(2024, 9, 1), date(2025, 7, 31), AcademicYearStatus.ARCHIVED),
    ("2025-2026", date(2025, 9, 1), date(2026, 7, 31), AcademicYearStatus.ACTIVE),
    ("2026-2027", date(2026, 9, 1), date(2027, 7, 31), AcademicYearStatus.ACTIVE),
]

CATEGORIES = [
    ("LICENCE", t("Licence", "Bachelor", "الإجازة"), 10),
    ("MASTER", t("Master", "Master", "الماستر"), 20),
    ("DOCTORAT", t("Doctorat", "Doctorate", "الدكتوراه"), 30),
    ("FORMATION_CONTINUE", t("Formation continue", "Continuing education", "التكوين المستمر"), 40),
]

BRANCHES = {
    "LICENCE": [
        ("INFO", t("Informatique", "Computer Science", "الإعلاميات")),
        ("MATH", t("Mathématiques", "Mathematics", "الرياضيات")),
        ("PHYS", t("Physique", "Physics", "الفيزياء")),
    ],
    "MASTER": [
        ("GL", t("Génie logiciel", "Software Engineering", "هندسة البرمجيات")),
        ("IA", t("Intelligence artificielle", "Artificial Intelligence", "الذكاء الاصطناعي")),
        ("RES", t("Réseaux et systèmes", "Networks and Systems", "الشبكات والأنظمة")),
        ("DATA", t("Science des données", "Data Science", "علم البيانات")),
    ],
    "DOCTORAT": [
        ("INFO", t("Informatique", "Computer Science", "الإعلاميات")),
        ("MATH", t("Mathématiques appliquées", "Applied Mathematics", "الرياضيات التطبيقية")),
    ],
    "FORMATION_CONTINUE": [
        (
            "MSI",
            t(
                "Management des systèmes d'information",
                "Information Systems Management",
                "تدبير نظم المعلومات",
            ),
        ),
    ],
}

LEVELS = {
    "LICENCE": [
        ("L1", t("1re année", "1st year", "السنة الأولى")),
        ("L2", t("2e année", "2nd year", "السنة الثانية")),
        ("L3", t("3e année", "3rd year", "السنة الثالثة")),
    ],
    "MASTER": [
        ("M1", t("1re année", "1st year", "السنة الأولى")),
        ("M2", t("2e année", "2nd year", "السنة الثانية")),
    ],
    "DOCTORAT": [
        ("D1", t("1re année", "1st year", "السنة الأولى")),
        ("D2", t("2e année", "2nd year", "السنة الثانية")),
        ("D3", t("3e année", "3rd year", "السنة الثالثة")),
    ],
    "FORMATION_CONTINUE": [("FC1", t("Année unique", "Single year", "سنة واحدة"))],
}

# code, name, delivery, requires_attachment, max_qty, processing_days, restricted categories
DOCUMENT_TYPES = [
    (
        "ATTESTATION_SCOLARITE",
        t("Attestation de scolarité", "Certificate of enrollment", "شهادة التمدرس"),
        DeliveryMode.DIGITAL,
        False,
        3,
        2,
        [],
    ),
    (
        "CERTIFICAT_SCOLARITE",
        t("Certificat de scolarité", "School certificate", "شهادة مدرسية"),
        DeliveryMode.DIGITAL,
        False,
        3,
        2,
        [],
    ),
    ("RELEVE_NOTES", t("Relevé de notes", "Transcript", "كشف النقط"), DeliveryMode.DIGITAL, False, 3, 5, []),
    (
        "ATTESTATION_REUSSITE",
        t("Attestation de réussite", "Certificate of achievement", "شهادة النجاح"),
        DeliveryMode.DIGITAL,
        False,
        2,
        5,
        [],
    ),
    ("DIPLOME", t("Diplôme", "Diploma", "الدبلوم"), DeliveryMode.PICKUP, True, 1, 30, []),
    (
        "CERTIFICAT_STAGE",
        t("Certificat de stage", "Internship certificate", "شهادة التدريب"),
        DeliveryMode.DIGITAL,
        True,
        1,
        5,
        ["LICENCE", "MASTER"],
    ),
    (
        "CONVENTION_STAGE",
        t("Convention de stage", "Internship agreement", "اتفاقية التدريب"),
        DeliveryMode.PICKUP,
        True,
        3,
        7,
        ["LICENCE", "MASTER"],
    ),
    (
        "ATTESTATION_FORMATION",
        t("Attestation de formation", "Training certificate", "شهادة التكوين"),
        DeliveryMode.DIGITAL,
        False,
        1,
        5,
        ["FORMATION_CONTINUE"],
    ),
    ("AUTRE", t("Autre document", "Other document", "وثيقة أخرى"), DeliveryMode.DIGITAL, False, 1, 10, []),
]


async def _upsert(db: AsyncSession, model, where: dict, values: dict):
    obj = await db.scalar(select(model).filter_by(**where))
    if obj is None:
        obj = model(**where, **values)
        db.add(obj)
    else:
        for k, v in values.items():
            setattr(obj, k, v)
    await db.flush()
    return obj


async def _ensure_user(
    db: AsyncSession, email: str, role: Role, first: str, last: str, password: str
) -> User:
    user = await db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(
            email=email,
            role=role,
            first_name=first,
            last_name=last,
            password_hash=hash_password(password),
            is_active=True,
            failed_login_count=0,
            email_verified_at=datetime.now(UTC),
        )
        user.identities.append(AuthIdentity(provider=IdentityProvider.LOCAL, subject=email))
        db.add(user)
        await db.flush()
        logger.info("Created %s account %s", role.value, email)
    return user


async def seed(db: AsyncSession, *, student_domain: str, demo_password: str | None) -> None:
    years = {}
    for label, start, end, status in YEARS:
        years[label] = await _upsert(
            db, AcademicYear, {"label": label}, {"start_date": start, "end_date": end, "status": status}
        )

    categories = {}
    for code, name, order in CATEGORIES:
        categories[code] = await _upsert(
            db, BranchCategory, {"code": code}, {"name_i18n": name, "sort_order": order, "is_active": True}
        )

    branches = {}
    for cat_code, items in BRANCHES.items():
        for code, name in items:
            branches[(cat_code, code)] = await _upsert(
                db,
                Branch,
                {"category_id": categories[cat_code].id, "code": code},
                {"name_i18n": name, "is_active": True},
            )

    levels = {}
    for cat_code, items in LEVELS.items():
        for order, (code, name) in enumerate(items, start=1):
            levels[(cat_code, code)] = await _upsert(
                db,
                StudyLevel,
                {"category_id": categories[cat_code].id, "code": code},
                {"name_i18n": name, "sort_order": order, "is_active": True},
            )

    for code, name, delivery, attachment, max_qty, days, restricted in DOCUMENT_TYPES:
        doc = await _upsert(
            db,
            DocumentType,
            {"code": code},
            {
                "name_i18n": name,
                "delivery_mode": delivery,
                "requires_attachment": attachment,
                "max_quantity": max_qty,
                "processing_days": days,
                "is_active": True,
            },
        )
        await db.refresh(doc, ["allowed_categories"])
        doc.allowed_categories = [categories[c] for c in restricted]

    await _upsert(db, AllowedEmailDomain, {"domain": student_domain}, {"is_active": True})

    if demo_password:
        await _ensure_user(db, "superadmin@univ-demo.ma", Role.SUPER_ADMIN, "Salma", "Bennani", demo_password)
        await _ensure_user(db, "admin@univ-demo.ma", Role.ADMIN, "Youssef", "Amrani", demo_password)
        student_user = await _ensure_user(
            db, f"etudiant@{student_domain}", Role.STUDENT, "Ahmed", "Alaoui", demo_password
        )
        student = await _upsert(db, Student, {"user_id": student_user.id}, {"student_number": "D130000001"})
        await _upsert(
            db,
            StudentEnrollment,
            {
                "student_id": student.id,
                "academic_year_id": years["2026-2027"].id,
                "branch_id": branches[("MASTER", "IA")].id,
            },
            # Demo enrollment is pre-verified so the demo student can submit requests right away.
            {
                "study_level_id": levels[("MASTER", "M1")].id,
                "status": EnrollmentStatus.VERIFIED,
                "source": EnrollmentSource.ADMIN,
            },
        )
    await db.commit()


async def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    if settings.is_production:
        logger.error("Refusing to seed demo data in production")
        return 1
    engine = create_engine(settings.database_url)
    try:
        async with create_sessionmaker(engine)() as db:
            await seed(
                db,
                student_domain=os.environ.get("SEED_STUDENT_EMAIL_DOMAIN", "etu.univ-demo.ma"),
                demo_password=os.environ.get("SEED_DEMO_PASSWORD") or None,
            )
    finally:
        await engine.dispose()
    logger.info("Seed completed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
