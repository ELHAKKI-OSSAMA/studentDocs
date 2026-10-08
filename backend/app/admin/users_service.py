import uuid
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.schemas import AdminCreate, UserOut, UserUpdate
from app.auth.service import revoke_all_sessions
from app.core.crud import PageParams, commit_or_conflict, paginate
from app.core.errors import AppError, NotFoundError
from app.core.security import hash_password
from app.users.models import AuthIdentity, IdentityProvider, Role, User


def to_user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        role=user.role,
        first_name=user.first_name,
        last_name=user.last_name,
        is_active=user.is_active,
        email_verified=user.email_verified_at is not None,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


class UserAdminService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def search(self, role: Role | None, query: str | None, params: PageParams):
        stmt = select(User).order_by(User.created_at.desc())
        if role:
            stmt = stmt.where(User.role == role)
        if query:
            like = f"%{query.strip()}%"
            stmt = stmt.where(
                or_(User.email.ilike(like), func.concat(User.first_name, " ", User.last_name).ilike(like))
            )
        return await paginate(self.db, stmt, params)

    async def create_staff(self, data: AdminCreate) -> User:
        email = data.email.lower()
        user = User(
            email=email,
            password_hash=hash_password(data.password),
            role=data.role,
            first_name=data.first_name,
            last_name=data.last_name,
            is_active=True,
            failed_login_count=0,
            # Created by a super-admin who vouches for the address.
            email_verified_at=datetime.now(UTC),
        )
        user.identities.append(AuthIdentity(provider=IdentityProvider.LOCAL, subject=email))
        self.db.add(user)
        await commit_or_conflict(self.db)
        return user

    async def _active_super_admins(self) -> int:
        return int(
            await self.db.scalar(
                select(func.count())
                .select_from(User)
                .where(User.role == Role.SUPER_ADMIN, User.is_active.is_(True))
            )
            or 0
        )

    async def update(self, actor: User, user_id: uuid.UUID, data: UserUpdate) -> User:
        user = await self.db.get(User, user_id)
        if user is None:
            raise NotFoundError("User not found")
        if user.id == actor.id:
            raise AppError.of(422, "cannot_modify_self", "You cannot change your own role or status")
        if data.role is not None and user.role == Role.STUDENT:
            raise AppError.of(422, "invalid_role_change", "Student accounts cannot be promoted to staff")

        removes_super_admin = (
            user.role == Role.SUPER_ADMIN
            and user.is_active
            and (data.is_active is False or (data.role is not None and data.role != Role.SUPER_ADMIN))
        )
        if removes_super_admin and await self._active_super_admins() <= 1:
            raise AppError.of(422, "last_super_admin", "At least one active super-admin is required")

        changed_security = False
        if data.is_active is not None and data.is_active != user.is_active:
            user.is_active = data.is_active
            changed_security = True
        if data.role is not None and data.role != user.role:
            user.role = data.role
            changed_security = True
        if changed_security:
            # New permissions or deactivation apply immediately: existing sessions are revoked.
            await revoke_all_sessions(self.db, user)
        await commit_or_conflict(self.db)
        return user
