import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.auth.dependencies import Requires
from app.auth.permissions import Perm
from app.core.crud import Page, PageParams
from app.core.deps import ClientIp, DbSession
from app.students.models import EnrollmentStatus
from app.students.schemas import (
    EnrollmentIn,
    EnrollmentOut,
    EnrollmentReview,
    EnrollmentReviewItem,
    StudentDetail,
    StudentListItem,
)
from app.students.service import StudentService, to_list_item

router = APIRouter(prefix="/api/v1/students/me", tags=["students"])
admin_router = APIRouter(prefix="/api/v1/admin/students", tags=["admin-students"])
enrollments_admin_router = APIRouter(prefix="/api/v1/admin/enrollments", tags=["admin-enrollments"])

EnrollmentOwner = Requires(Perm.ENROLLMENT_SELF)
StudentsReader = Requires(Perm.ADMIN_ACCESS, Perm.STUDENTS_READ)
EnrollmentReviewer = Requires(Perm.ADMIN_ACCESS, Perm.ENROLLMENTS_VERIFY)


@router.get("/enrollments", response_model=list[EnrollmentOut])
async def my_enrollments(db: DbSession, current: EnrollmentOwner):
    service = StudentService(db)
    student = await service.for_user(current.id)
    return await service.enrollments(student.id)


@router.post("/enrollments", response_model=EnrollmentOut, status_code=status.HTTP_201_CREATED)
async def add_my_enrollment(data: EnrollmentIn, db: DbSession, current: EnrollmentOwner):
    service = StudentService(db)
    student = await service.for_user(current.id)
    return await service.add_enrollment(student.id, data)


@router.delete("/enrollments/{enrollment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_my_enrollment(enrollment_id: uuid.UUID, db: DbSession, current: EnrollmentOwner) -> Response:
    service = StudentService(db)
    student = await service.for_user(current.id)
    await service.remove_enrollment(student.id, enrollment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.get("", response_model=Page[StudentListItem])
async def list_students(
    db: DbSession,
    _: StudentsReader,
    params: Annotated[PageParams, Depends()],
    q: Annotated[str | None, Query(max_length=100)] = None,
):
    students, total = await StudentService(db).search(q, params)
    return Page(
        items=[to_list_item(s) for s in students], total=total, limit=params.limit, offset=params.offset
    )


@admin_router.get("/{student_id}", response_model=StudentDetail)
async def get_student(student_id: uuid.UUID, db: DbSession, _: StudentsReader):
    service = StudentService(db)
    student = await service.get(student_id)
    enrollments = await service.enrollments(student.id)
    return StudentDetail(
        **to_list_item(student).model_dump(),
        enrollments=[EnrollmentOut.model_validate(e) for e in enrollments],
    )


def _review_item(e) -> EnrollmentReviewItem:
    user = e.student.user
    return EnrollmentReviewItem(
        **EnrollmentOut.model_validate(e).model_dump(),
        student_id=e.student_id,
        student_name=f"{user.first_name} {user.last_name}",
        student_email=user.email,
        student_number=e.student.student_number,
        reviewer_name=f"{e.reviewed_by.first_name} {e.reviewed_by.last_name}" if e.reviewed_by else None,
    )


@enrollments_admin_router.get("", response_model=Page[EnrollmentReviewItem])
async def enrollment_queue(
    db: DbSession,
    _: EnrollmentReviewer,
    params: Annotated[PageParams, Depends()],
    status_filter: Annotated[EnrollmentStatus | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
):
    rows, total = await StudentService(db).review_queue(status_filter, q, params)
    return Page(items=[_review_item(e) for e in rows], total=total, limit=params.limit, offset=params.offset)


@enrollments_admin_router.patch("/{enrollment_id}", response_model=EnrollmentReviewItem)
async def review_enrollment(
    enrollment_id: uuid.UUID, data: EnrollmentReview, db: DbSession, current: EnrollmentReviewer, ip: ClientIp
):
    return _review_item(await StudentService(db).review(enrollment_id, data, current.user, ip))
