import ipaddress
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import revoked_jti_key
from app.auth.emails import verification_email
from app.auth.schemas import RegisterIn
from app.core.config import Settings
from app.core.errors import AppError, ConflictError
from app.core.mailer import queue_email
from app.core.ratelimit import RateLimitedError, RateLimiter
from app.core.security import (
    create_access_token,
    generate_token,
    hash_password,
    hash_token,
    password_needs_rehash,
    verify_password,
)
from app.students.models import Student
from app.users.models import (
    AllowedEmailDomain,
    AuthIdentity,
    EmailVerificationToken,
    IdentityProvider,
    RefreshToken,
    Role,
    User,
)


class AuthError(AppError):
    status_code = 401
    code = "invalid_credentials"


class AccountStateError(AppError):
    status_code = 403


@dataclass(frozen=True)
class SessionTokens:
    access: str
    refresh: str
    csrf: str
    user: User


def _now() -> datetime:
    return datetime.now(UTC)


def _ip_or_none(ip: str | None) -> str | None:
    try:
        return str(ipaddress.ip_address(ip)) if ip else None
    except ValueError:
        return None


async def revoke_all_sessions(db: AsyncSession, user: User) -> None:
    """Revokes every refresh token and invalidates outstanding access tokens. Caller commits."""
    now = _now()
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    user.sessions_revoked_at = now


class AuthService:
    def __init__(self, db: AsyncSession, settings: Settings, limiter: RateLimiter, redis: Redis) -> None:
        self.db = db
        self.settings = settings
        self.limiter = limiter
        self.redis = redis

    # --- registration -------------------------------------------------------------------------

    async def _is_allowed_domain(self, email: str) -> bool:
        domain = email.rsplit("@", 1)[1].lower()
        found = await self.db.scalar(
            select(AllowedEmailDomain.id).where(
                AllowedEmailDomain.domain == domain, AllowedEmailDomain.is_active.is_(True)
            )
        )
        return found is not None

    async def _get_user_by_email(self, email: str) -> User | None:
        return await self.db.scalar(select(User).where(User.email == email))

    async def _send_verification(self, user: User) -> None:
        token = generate_token()
        now = _now()
        self.db.add(
            EmailVerificationToken(
                user_id=user.id,
                token_hash=hash_token(token),
                created_at=now,
                expires_at=now + timedelta(seconds=self.settings.email_verification_ttl_seconds),
            )
        )
        await self.db.commit()
        link = f"{self.settings.frontend_url}/{user.locale.value}/verify-email?{urlencode({'token': token})}"
        queue_email(
            verification_email(
                to=user.email,
                name=user.first_name,
                locale=user.locale,
                link=link,
                ttl_seconds=self.settings.email_verification_ttl_seconds,
            )
        )

    async def register(self, data: RegisterIn, ip: str) -> None:
        s = self.settings
        await self.limiter.hit(
            "register",
            ip,
            limit=s.rate_limit_register_per_ip,
            window_seconds=s.rate_limit_register_window_seconds,
        )
        email = data.email.lower()
        if not await self._is_allowed_domain(email):
            raise AppError.of(
                422, "email_domain_not_allowed", "Registration requires an institutional email address"
            )

        existing = await self._get_user_by_email(email)
        if existing is not None:
            # Same response whether or not the account exists (no account enumeration).
            if existing.email_verified_at is None and existing.is_active:
                await self._send_verification(existing)
            return

        user = User(
            email=email,
            password_hash=hash_password(data.password),
            role=Role.STUDENT,
            first_name=data.first_name,
            last_name=data.last_name,
            locale=data.locale,
            is_active=True,
            failed_login_count=0,
        )
        user.identities.append(AuthIdentity(provider=IdentityProvider.LOCAL, subject=email))
        self.db.add(user)
        try:
            await self.db.flush()
            self.db.add(Student(user_id=user.id, student_number=data.student_number))
            await self.db.flush()
        except IntegrityError as exc:
            await self.db.rollback()
            if "student_number" in str(exc.orig):
                raise ConflictError("This student number is already registered") from exc
            return  # concurrent registration of the same email: treated like an existing account
        await self._send_verification(user)

    async def resend_verification(self, email: str, ip: str) -> None:
        s = self.settings
        await self.limiter.hit(
            "resend",
            ip,
            limit=s.rate_limit_register_per_ip,
            window_seconds=s.rate_limit_register_window_seconds,
        )
        user = await self._get_user_by_email(email.lower())
        if user is not None and user.email_verified_at is None and user.is_active:
            await self._send_verification(user)

    async def verify_email(self, token: str) -> None:
        row = await self.db.scalar(
            select(EmailVerificationToken)
            .where(EmailVerificationToken.token_hash == hash_token(token))
            .with_for_update()
        )
        now = _now()
        if row is None or row.used_at is not None or row.expires_at <= now:
            raise AppError.of(400, "invalid_token", "This verification link is invalid or has expired")
        user = await self.db.get(User, row.user_id)
        row.used_at = now
        if user.email_verified_at is None:
            user.email_verified_at = now
        await self.db.commit()

    # --- sessions -----------------------------------------------------------------------------

    async def _issue_session(
        self, user: User, *, family_id: uuid.UUID, ip: str | None, user_agent: str | None
    ) -> SessionTokens:
        now = _now()
        refresh = generate_token()
        self.db.add(
            RefreshToken(
                user_id=user.id,
                family_id=family_id,
                token_hash=hash_token(refresh),
                created_at=now,
                expires_at=now + timedelta(seconds=self.settings.refresh_token_ttl_seconds),
                ip=_ip_or_none(ip),
                user_agent=(user_agent or "")[:255] or None,
            )
        )
        access, _ = create_access_token(
            user_id=user.id,
            role=user.role.value,
            secret=self.settings.secret_key.get_secret_value(),
            ttl_seconds=self.settings.access_token_ttl_seconds,
        )
        await self.db.commit()
        return SessionTokens(access=access, refresh=refresh, csrf=generate_token(), user=user)

    async def login(self, email: str, password: str, ip: str, user_agent: str | None) -> SessionTokens:
        s = self.settings
        await self.limiter.hit(
            "login", ip, limit=s.rate_limit_login_per_ip, window_seconds=s.rate_limit_login_window_seconds
        )
        user = await self._get_user_by_email(email.lower())
        now = _now()
        if user is not None and user.locked_until and user.locked_until > now:
            retry = int((user.locked_until - now).total_seconds()) + 1
            raise RateLimitedError(
                "Too many failed attempts, account temporarily locked", {"retry_after": retry}
            )

        if not verify_password(user.password_hash if user else None, password):
            if user is not None:
                user.failed_login_count += 1
                if user.failed_login_count >= s.login_max_failed_attempts:
                    user.locked_until = now + timedelta(seconds=s.login_lockout_seconds)
                    user.failed_login_count = 0
                await self.db.commit()
            raise AuthError("Invalid email or password")

        # State checks only after a correct password, so they never reveal account existence.
        if not user.is_active:
            raise AccountStateError.of(403, "account_disabled", "This account has been disabled")
        if user.email_verified_at is None:
            raise AccountStateError.of(403, "email_not_verified", "Please verify your email address first")

        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = now
        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        await self.db.execute(
            update(AuthIdentity)
            .where(AuthIdentity.user_id == user.id, AuthIdentity.provider == IdentityProvider.LOCAL)
            .values(last_used_at=now)
        )
        return await self._issue_session(user, family_id=uuid.uuid4(), ip=ip, user_agent=user_agent)

    async def _revoke_family(self, family_id: uuid.UUID) -> None:
        await self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=_now())
        )
        await self.db.commit()

    async def refresh(self, refresh_token: str, ip: str, user_agent: str | None) -> SessionTokens:
        row = await self.db.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(refresh_token)).with_for_update()
        )
        now = _now()
        if row is None:
            raise AuthError.of(401, "invalid_refresh_token", "Session expired, please sign in again")
        if row.revoked_at is not None or row.rotated_at is not None:
            # A rotated/revoked token was presented again: likely stolen. Kill the whole session family.
            await self._revoke_family(row.family_id)
            raise AuthError.of(401, "refresh_token_reused", "Session revoked, please sign in again")
        if row.expires_at <= now:
            raise AuthError.of(401, "invalid_refresh_token", "Session expired, please sign in again")

        user = await self.db.get(User, row.user_id)
        if user is None or not user.is_active or user.email_verified_at is None:
            await self._revoke_family(row.family_id)
            raise AuthError.of(401, "invalid_refresh_token", "Session expired, please sign in again")

        row.rotated_at = now
        return await self._issue_session(user, family_id=row.family_id, ip=ip, user_agent=user_agent)

    async def logout(self, refresh_token: str | None, access_claims: dict | None) -> None:
        if refresh_token:
            row = await self.db.scalar(
                select(RefreshToken).where(RefreshToken.token_hash == hash_token(refresh_token))
            )
            if row is not None:
                await self._revoke_family(row.family_id)
        if access_claims:
            ttl = int(access_claims["exp"] - _now().timestamp())
            if ttl > 0:
                await self.redis.set(
                    revoked_jti_key(self.settings.redis_key_prefix, access_claims["jti"]), "1", ex=ttl
                )

    async def logout_everywhere(self, user: User) -> None:
        await revoke_all_sessions(self.db, user)
        await self.db.commit()
