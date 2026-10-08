import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, select

from app.academic.models import AcademicYear, AcademicYearStatus, Branch, DocumentType
from app.admin.schemas import (
    AdminCreate,
    DashboardStats,
    EmailDomainIn,
    EmailDomainOut,
    UserOut,
    UserUpdate,
)
from app.admin.users_service import UserAdminService, to_user_out
from app.auth.dependencies import Requires
from app.auth.permissions import Perm
from app.core.crud import Page, PageParams, commit_or_conflict
from app.core.deps import DbSession
from app.core.errors import NotFoundError
from app.requests.models import TERMINAL_STATUSES, Request, RequestStatus
from app.students.models import EnrollmentStatus, StudentEnrollment
from app.users.models import AllowedEmailDomain, Role, User

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

DashboardReader = Requires(Perm.ADMIN_ACCESS, Perm.DASHBOARD_READ)
UsersReader = Requires(Perm.ADMIN_ACCESS, Perm.USERS_READ)
UsersManager = Requires(Perm.ADMIN_ACCESS, Perm.USERS_MANAGE)
SettingsManager = Requires(Perm.ADMIN_ACCESS, Perm.SETTINGS_MANAGE)


async def _count(db: DbSession, stmt) -> int:
    return int(await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)


@router.get("/dashboard", response_model=DashboardStats)
async def dashboard(db: DbSession, current: DashboardReader) -> DashboardStats:
    students = select(User.id).where(User.role == Role.STUDENT)
    by_status = dict((await db.execute(select(Request.status, func.count()).group_by(Request.status))).all())
    open_requests = select(Request.id).where(Request.status.not_in(TERMINAL_STATUSES))
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return DashboardStats(
        requests_today=await _count(db, select(Request.id).where(Request.created_at >= today)),
        requests_open=await _count(db, open_requests),
        requests_unassigned=await _count(db, open_requests.where(Request.assigned_to_id.is_(None))),
        requests_needing_information=by_status.get(RequestStatus.NEEDS_INFORMATION, 0),
        requests_assigned_to_me=await _count(db, open_requests.where(Request.assigned_to_id == current.id)),
        enrollments_pending=await _count(
            db, select(StudentEnrollment.id).where(StudentEnrollment.status == EnrollmentStatus.PENDING)
        ),
        requests_by_status={status.value: by_status.get(status, 0) for status in RequestStatus},
        students_total=await _count(db, students),
        students_pending_verification=await _count(db, students.where(User.email_verified_at.is_(None))),
        staff_total=await _count(db, select(User.id).where(User.role.in_([Role.ADMIN, Role.SUPER_ADMIN]))),
        active_academic_years=await _count(
            db, select(AcademicYear.id).where(AcademicYear.status == AcademicYearStatus.ACTIVE)
        ),
        active_branches=await _count(db, select(Branch.id).where(Branch.is_active.is_(True))),
        active_document_types=await _count(
            db, select(DocumentType.id).where(DocumentType.is_active.is_(True))
        ),
        allowed_email_domains=await _count(
            db, select(AllowedEmailDomain.id).where(AllowedEmailDomain.is_active.is_(True))
        ),
    )


# --- users -----------------------------------------------------------------------------------------


@router.get("/users", response_model=Page[UserOut])
async def list_users(
    db: DbSession,
    _: UsersReader,
    params: Annotated[PageParams, Depends()],
    role: Role | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
):
    users, total = await UserAdminService(db).search(role, q, params)
    return Page(items=[to_user_out(u) for u in users], total=total, limit=params.limit, offset=params.offset)


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_staff(data: AdminCreate, db: DbSession, _: UsersManager):
    return to_user_out(await UserAdminService(db).create_staff(data))


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(user_id: uuid.UUID, data: UserUpdate, db: DbSession, current: UsersManager):
    return to_user_out(await UserAdminService(db).update(current.user, user_id, data))


# --- settings: institutional email domains ---------------------------------------------------------


@router.get("/settings/email-domains", response_model=list[EmailDomainOut])
async def list_domains(db: DbSession, _: SettingsManager):
    return (await db.scalars(select(AllowedEmailDomain).order_by(AllowedEmailDomain.domain))).all()


@router.post("/settings/email-domains", response_model=EmailDomainOut, status_code=status.HTTP_201_CREATED)
async def add_domain(data: EmailDomainIn, db: DbSession, _: SettingsManager):
    domain = AllowedEmailDomain(domain=data.domain, is_active=True)
    db.add(domain)
    await commit_or_conflict(db)
    return domain


@router.delete("/settings/email-domains/{domain_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_domain(domain_id: uuid.UUID, db: DbSession, _: SettingsManager) -> Response:
    domain = await db.get(AllowedEmailDomain, domain_id)
    if domain is None:
        raise NotFoundError("Domain not found")
    await db.delete(domain)
    await commit_or_conflict(db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
