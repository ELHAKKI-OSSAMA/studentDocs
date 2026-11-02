from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.auth.cookies import (
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    clear_session_cookies,
    set_session_cookies,
)
from app.auth.dependencies import CurrentUserDep, Requires, load_permissions
from app.auth.permissions import Perm
from app.auth.schemas import (
    AcceptedOut,
    EmailIn,
    LoginIn,
    MeOut,
    MeUpdate,
    RegisterIn,
    StudentSummary,
    TokenIn,
)
from app.auth.service import AuthService, SessionTokens
from app.core.deps import ClientIp, DbSession, EphemeralDep, RateLimiterDep, SettingsDep
from app.core.errors import AppError
from app.core.security import decode_access_token
from app.students.models import Student
from app.users.models import User

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def get_auth_service(
    db: DbSession, settings: SettingsDep, limiter: RateLimiterDep, ephemeral: EphemeralDep
) -> AuthService:
    return AuthService(db, settings, limiter, ephemeral)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


async def build_me(db: DbSession, user: User, permissions: frozenset[str] | None = None) -> MeOut:
    perms = permissions if permissions is not None else await load_permissions(db, user)
    student = await db.scalar(select(Student).where(Student.user_id == user.id))
    return MeOut(
        id=user.id,
        email=user.email,
        role=user.role,
        first_name=user.first_name,
        last_name=user.last_name,
        locale=user.locale,
        permissions=sorted(perms),
        student=StudentSummary.model_validate(student) if student else None,
    )


async def _session_response(db: DbSession, settings: SettingsDep, tokens: SessionTokens) -> JSONResponse:
    me = await build_me(db, tokens.user)
    response = JSONResponse(me.model_dump(mode="json"))
    set_session_cookies(
        response,
        settings,
        access=tokens.access,
        refresh=tokens.refresh,
        csrf=tokens.csrf,
        role=tokens.user.role,
    )
    return response


@router.post("/register", status_code=status.HTTP_202_ACCEPTED, response_model=AcceptedOut)
async def register(data: RegisterIn, service: AuthServiceDep, ip: ClientIp) -> AcceptedOut:
    await service.register(data, ip)
    return AcceptedOut()


@router.post("/verify-email", response_model=AcceptedOut)
async def verify_email(data: TokenIn, service: AuthServiceDep) -> AcceptedOut:
    await service.verify_email(data.token)
    return AcceptedOut(status="verified")


@router.post("/resend-verification", status_code=status.HTTP_202_ACCEPTED, response_model=AcceptedOut)
async def resend_verification(data: EmailIn, service: AuthServiceDep, ip: ClientIp) -> AcceptedOut:
    await service.resend_verification(data.email, ip)
    return AcceptedOut()


@router.post("/login", response_model=MeOut)
async def login(
    data: LoginIn,
    request: Request,
    service: AuthServiceDep,
    db: DbSession,
    settings: SettingsDep,
    ip: ClientIp,
) -> JSONResponse:
    tokens = await service.login(data.email, data.password, ip, request.headers.get("user-agent"))
    return await _session_response(db, settings, tokens)


@router.post("/refresh", response_model=MeOut)
async def refresh(
    request: Request, service: AuthServiceDep, db: DbSession, settings: SettingsDep, ip: ClientIp
) -> JSONResponse:
    token = request.cookies.get(REFRESH_COOKIE)
    try:
        if not token:
            raise AppError.of(401, "invalid_refresh_token", "Session expired, please sign in again")
        tokens = await service.refresh(token, ip, request.headers.get("user-agent"))
    except AppError as exc:
        # Failed refresh: drop every session cookie so the client cleanly falls back to the login page.
        response = JSONResponse(
            {
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": None,
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
            status_code=exc.status_code,
        )
        clear_session_cookies(response, settings)
        return response
    return await _session_response(db, settings, tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, service: AuthServiceDep, settings: SettingsDep) -> Response:
    access = request.cookies.get(ACCESS_COOKIE)
    claims = decode_access_token(access, settings.secret_key.get_secret_value()) if access else None
    await service.logout(request.cookies.get(REFRESH_COOKIE), claims)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookies(response, settings)
    return response


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(current: CurrentUserDep, service: AuthServiceDep, settings: SettingsDep) -> Response:
    await service.logout_everywhere(current.user)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookies(response, settings)
    return response


@router.get("/me", response_model=MeOut)
async def me(current: CurrentUserDep, db: DbSession) -> MeOut:
    return await build_me(db, current.user, current.permissions)


@router.patch("/me", response_model=MeOut)
async def update_me(data: MeUpdate, current: Requires(Perm.PROFILE_SELF), db: DbSession) -> MeOut:
    for field, value in data.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(current.user, field, value)
    await db.commit()
    return await build_me(db, current.user, current.permissions)
