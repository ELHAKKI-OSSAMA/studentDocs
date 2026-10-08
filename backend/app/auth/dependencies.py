import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select

from app.auth.cookies import ACCESS_COOKIE
from app.auth.permissions import Perm
from app.core.deps import DbSession, RedisDep, SettingsDep
from app.core.errors import AppError, PermissionDeniedError
from app.core.security import decode_access_token
from app.users.models import RolePermission, User


class NotAuthenticatedError(AppError):
    status_code = 401
    code = "not_authenticated"


@dataclass(frozen=True)
class CurrentUser:
    user: User
    permissions: frozenset[str]

    @property
    def id(self) -> uuid.UUID:
        return self.user.id

    def has(self, perm: Perm) -> bool:
        return perm.value in self.permissions


def revoked_jti_key(prefix: str, jti: str) -> str:
    return f"{prefix}revoked_jti:{jti}"


async def load_permissions(db: DbSession, user: User) -> frozenset[str]:
    rows = await db.scalars(select(RolePermission.permission_code).where(RolePermission.role == user.role))
    return frozenset(rows.all())


async def get_current_user(
    request: Request, db: DbSession, settings: SettingsDep, redis: RedisDep
) -> CurrentUser:
    token = request.cookies.get(ACCESS_COOKIE)
    claims = decode_access_token(token, settings.secret_key.get_secret_value()) if token else None
    if claims is None:
        raise NotAuthenticatedError("Authentication required")
    if await redis.exists(revoked_jti_key(settings.redis_key_prefix, claims["jti"])):
        raise NotAuthenticatedError("Session has ended")
    try:
        user = await db.get(User, uuid.UUID(claims["sub"]))
    except ValueError:
        user = None
    # Account state is re-checked on every request: deactivation takes effect immediately.
    if user is None or not user.is_active or user.email_verified_at is None:
        raise NotAuthenticatedError("Authentication required")
    if user.sessions_revoked_at and claims.get("iat_ms", 0) <= user.sessions_revoked_at.timestamp() * 1000:
        raise NotAuthenticatedError("Session has ended")
    if claims.get("role") != user.role.value:
        raise NotAuthenticatedError("Session is outdated")
    request.state.user_id = user.id
    return CurrentUser(user=user, permissions=await load_permissions(db, user))


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


def require_permission(*perms: Perm):
    """Dependency factory: the caller must hold every listed permission."""

    async def _check(current: CurrentUserDep) -> CurrentUser:
        missing = [p.value for p in perms if p.value not in current.permissions]
        if missing:
            raise PermissionDeniedError("You do not have permission to perform this action")
        return current

    return _check


def Requires(*perms: Perm):  # noqa: N802 — reads like a type in route signatures
    return Annotated[CurrentUser, Depends(require_permission(*perms))]
