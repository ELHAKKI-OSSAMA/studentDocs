"""Password hashing, opaque tokens and access JWTs."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()  # argon2id with library-recommended parameters

# Verified against when the account does not exist, so response time does not reveal it.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))

JWT_ALGORITHM = "HS256"
# Tolerates small clock adjustments (e.g. VM/container time sync) on `iat` / `exp`.
JWT_LEEWAY_SECONDS = 5


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def generate_token() -> str:
    """High-entropy opaque token (refresh, email verification, CSRF)."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Opaque tokens are stored hashed; the plaintext only ever lives in the client."""
    return hashlib.sha256(token.encode()).hexdigest()


def create_access_token(*, user_id: uuid.UUID, role: str, secret: str, ttl_seconds: int) -> tuple[str, dict]:
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "jti": uuid.uuid4().hex,
        "iat": int(now.timestamp()),
        # Millisecond precision, compared with users.sessions_revoked_at.
        "iat_ms": int(now.timestamp() * 1000),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    return jwt.encode(claims, secret, algorithm=JWT_ALGORITHM), claims


def decode_access_token(token: str, secret: str) -> dict | None:
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "exp", "iat", "jti"]},
            leeway=JWT_LEEWAY_SECONDS,
        )
    except jwt.PyJWTError:
        return None
    return claims if claims.get("type") == "access" else None
