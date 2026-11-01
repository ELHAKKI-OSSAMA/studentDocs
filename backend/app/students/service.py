import uuid
from datetime import UTC, date, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.academic.models import AcademicYear, AcademicYearStatus, Branch, DocumentType, StudyLevel
from app.audit.service import record
from app.core.crud import PageParams, commit_or_conflict, paginate
from app.core.errors import AppError, NotFoundError
from app.students.models import (
    EnrollmentSource,
    EnrollmentStatus,
    Student,
    StudentDeposit,
    StudentEnrollment,
)
from app.students.schemas import DepositIn, EnrollmentIn, EnrollmentReview, StudentListItem
from app.users.models import User

MAX_ENROLLMENTS_PER_STUDENT = 20


def to_list_item(student: Student) -> StudentListItem:
    user = student.user
    return StudentListItem(
        id=student.id,
        user_id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        student_number=student.student_number,
        is_active=user.is_active,
        email_verified=user.email_verified_at is not None,
        created_at=student.created_at,
    )


class StudentService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def for_user(self, user_id: uuid.UUID) -> Student:
        student = await self.db.scalar(select(Student).where(Student.user_id == user_id))
        if student is None:
            raise NotFoundError("Student profile not found")
        return student

    async def get(self, student_id: uuid.UUID) -> Student:
        student = await self.db.get(Student, student_id)
        if student is None:
            raise NotFoundError("Student not found")
        return student

    async def search(self, query: str | None, params: PageParams) -> tuple[list[Student], int]:
        stmt = select(Student).join(Student.user).order_by(Student.created_at.desc())
        if query:
            like = f"%{query.strip()}%"
            stmt = stmt.where(
                or_(
                    User.email.ilike(like),
                    func.concat(User.first_name, " ", User.last_name).ilike(like),
                    Student.student_number.ilike(like),
                )
            )
        return await paginate(self.db, stmt, params)

    # --- enrollments (always scoped to one student: ownership is part of every query) ------------

    async def enrollments(self, student_id: uuid.UUID) -> list[StudentEnrollment]:
        stmt = (
            select(StudentEnrollment)
            .join(StudentEnrollment.academic_year)
            .where(StudentEnrollment.student_id == student_id)
            .order_by(AcademicYear.start_date.desc())
        )
        return list((await self.db.scalars(stmt)).unique().all())

    async def _check_refs(
        self, year_id: uuid.UUID, branch_id: uuid.UUID, level_id: uuid.UUID
    ) -> tuple[AcademicYear, Branch, StudyLevel]:
        year = await self.db.get(AcademicYear, year_id)
        branch = await self.db.get(Branch, branch_id)
        level = await self.db.get(StudyLevel, level_id)
        if year is None or year.status != AcademicYearStatus.ACTIVE:
            raise AppError.of(
                422, "invalid_reference", "Unknown or archived academic year", {"field": "academic_year_id"}
            )
        if branch is None or not branch.is_active or not branch.category.is_active:
            raise AppError.of(422, "invalid_reference", "Unknown or inactive branch", {"field": "branch_id"})
        if level is None or not level.is_active:
            raise AppError.of(
                422, "invalid_reference", "Unknown or inactive level", {"field": "study_level_id"}
            )
        if level.category_id != branch.category_id:
            raise AppError.of(
                422, "level_branch_mismatch", "This level does not belong to the branch category"
            )
        return year, branch, level

    async def add_enrollment(self, student_id: uuid.UUID, data: EnrollmentIn) -> StudentEnrollment:
        year, branch, level = await self._check_refs(
            data.academic_year_id, data.branch_id, data.study_level_id
        )
        count = await self.db.scalar(
            select(func.count())
            .select_from(StudentEnrollment)
            .where(StudentEnrollment.student_id == student_id)
        )
        if (count or 0) >= MAX_ENROLLMENTS_PER_STUDENT:
            raise AppError.of(422, "too_many_enrollments", "Enrollment limit reached")

        # Self-declared: PENDING until the administration verifies it.
        enrollment = StudentEnrollment(
            student_id=student_id,
            academic_year_id=year.id,
            branch_id=branch.id,
            study_level_id=level.id,
            status=EnrollmentStatus.PENDING,
            source=EnrollmentSource.SELF_DECLARED,
        )
        self.db.add(enrollment)
        await commit_or_conflict(self.db)
        return await self.db.get(StudentEnrollment, enrollment.id, populate_existing=True)

    async def remove_enrollment(self, student_id: uuid.UUID, enrollment_id: uuid.UUID) -> None:
        enrollment = await self.db.scalar(
            select(StudentEnrollment).where(
                StudentEnrollment.id == enrollment_id, StudentEnrollment.student_id == student_id
            )
        )
        # Another student's enrollment is indistinguishable from a missing one (404, not 403).
        if enrollment is None:
            raise NotFoundError("Enrollment not found")
        if enrollment.status == EnrollmentStatus.VERIFIED:
            raise AppError.of(
                409, "enrollment_verified", "A verified enrollment can only be changed by the administration"
            )
        await self.db.delete(enrollment)
        await commit_or_conflict(self.db)

    # --- administration review ----------------------------------------------------------------------

    async def review_queue(
        self, status: EnrollmentStatus | None, query: str | None, params: PageParams
    ) -> tuple[list[StudentEnrollment], int]:
        stmt = (
            select(StudentEnrollment)
            .join(Student, StudentEnrollment.student_id == Student.id)
            .join(User, Student.user_id == User.id)
            .order_by(StudentEnrollment.created_at.desc())
        )
        if status:
            stmt = stmt.where(StudentEnrollment.status == status)
        if query:
            like = f"%{query.strip()}%"
            stmt = stmt.where(
                or_(
                    User.email.ilike(like),
                    func.concat(User.first_name, " ", User.last_name).ilike(like),
                    Student.student_number.ilike(like),
                )
            )
        return await paginate(self.db, stmt, params)

    async def review(
        self, enrollment_id: uuid.UUID, data: EnrollmentReview, reviewer: User, ip: str | None
    ) -> StudentEnrollment:
        enrollment = await self.db.get(StudentEnrollment, enrollment_id)
        if enrollment is None:
            raise NotFoundError("Enrollment not found")
        note = (data.review_note or "").strip() or None
        if data.status == EnrollmentStatus.REJECTED and not note:
            raise AppError.of(422, "message_required", "A reason is required to reject an enrollment")
        corrections = {
            "academic_year_id": data.academic_year_id or enrollment.academic_year_id,
            "branch_id": data.branch_id or enrollment.branch_id,
            "study_level_id": data.study_level_id or enrollment.study_level_id,
        }
        changed = {k: str(v) for k, v in corrections.items() if getattr(enrollment, k) != v}
        if changed or data.status == EnrollmentStatus.VERIFIED:
            await self._check_refs(
                corrections["academic_year_id"], corrections["branch_id"], corrections["study_level_id"]
            )
        for field, value in corrections.items():
            setattr(enrollment, field, value)
        enrollment.status = data.status
        enrollment.review_note = note
        enrollment.reviewed_by_id = reviewer.id
        enrollment.reviewed_at = datetime.now(UTC)
        record(
            self.db,
            actor_id=reviewer.id,
            action="ENROLLMENT_REVIEWED",
            entity="enrollment",
            entity_id=enrollment.id,
            ip=ip,
            details={"status": data.status.value, "corrected": changed},
        )
        await commit_or_conflict(self.db)
        return await self.db.get(StudentEnrollment, enrollment.id, populate_existing=True)

    # --- deposited originals (recorded by staff; returning closes the deposit, history is kept) -----

    async def deposits(self, student_id: uuid.UUID, *, only_open: bool = False) -> list[StudentDeposit]:
        stmt = (
            select(StudentDeposit)
            .where(StudentDeposit.student_id == student_id)
            .order_by(StudentDeposit.returned_at.is_not(None), StudentDeposit.deposited_on.desc())
        )
        if only_open:
            stmt = stmt.where(StudentDeposit.returned_at.is_(None))
        return list((await self.db.scalars(stmt)).unique().all())

    async def add_deposit(
        self, student_id: uuid.UUID, data: DepositIn, actor: User, ip: str | None
    ) -> StudentDeposit:
        doc_type = await self.db.get(DocumentType, data.document_type_id)
        if doc_type is None or not doc_type.requires_deposit:
            raise AppError.of(
                422,
                "invalid_reference",
                "Unknown document type, or not one that is deposited",
                {"field": "document_type_id"},
            )
        if data.deposited_on > date.today():
            raise AppError.of(422, "invalid_date", "The deposit date cannot be in the future")
        already_open = await self.db.scalar(
            select(StudentDeposit.id).where(
                StudentDeposit.student_id == student_id,
                StudentDeposit.document_type_id == doc_type.id,
                StudentDeposit.returned_at.is_(None),
            )
        )
        if already_open:
            raise AppError.of(409, "deposit_exists", "This original is already recorded as deposited")
        deposit = StudentDeposit(
            id=uuid.uuid4(),
            student_id=student_id,
            document_type_id=doc_type.id,
            deposited_on=data.deposited_on,
            note=(data.note or "").strip() or None,
            recorded_by_id=actor.id,
        )
        self.db.add(deposit)
        record(
            self.db,
            actor_id=actor.id,
            action="DEPOSIT_RECORDED",
            entity="student",
            entity_id=student_id,
            ip=ip,
            details={"deposit_id": str(deposit.id), "document_type": doc_type.code},
        )
        # A concurrent second open deposit violates uq_student_deposits_open → 409.
        await commit_or_conflict(self.db)
        return await self.db.get(StudentDeposit, deposit.id, populate_existing=True)

    async def return_deposit(
        self, student_id: uuid.UUID, deposit_id: uuid.UUID, actor: User, ip: str | None
    ) -> StudentDeposit:
        deposit = await self.db.scalar(
            select(StudentDeposit).where(
                StudentDeposit.id == deposit_id, StudentDeposit.student_id == student_id
            )
        )
        if deposit is None:
            raise NotFoundError("Deposit not found")
        if deposit.returned_at is not None:
            raise AppError.of(409, "deposit_returned", "This original has already been returned")
        deposit.returned_at = datetime.now(UTC)
        deposit.returned_by_id = actor.id
        record(
            self.db,
            actor_id=actor.id,
            action="DEPOSIT_RETURNED",
            entity="student",
            entity_id=student_id,
            ip=ip,
            details={"deposit_id": str(deposit.id), "document_type": deposit.document_type.code},
        )
        await commit_or_conflict(self.db)
        return await self.db.get(StudentDeposit, deposit.id, populate_existing=True)
