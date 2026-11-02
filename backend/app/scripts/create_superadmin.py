"""Creates the first super-admin of a fresh deployment (the other admins are then created in the app).

Usage: python -m app.scripts.create_superadmin, with SUPERADMIN_EMAIL, SUPERADMIN_FIRST_NAME and
SUPERADMIN_LAST_NAME set.
The password is read from the SUPERADMIN_PASSWORD environment variable, or typed at the prompt (never as a
command-line argument, which would end up in the shell history).
"""

import asyncio
import getpass
import logging
import os
import sys

from sqlalchemy import select

from app.auth.schemas import PasswordPolicy
from app.core.config import get_settings
from app.core.db import create_engine, create_sessionmaker
from app.core.logging import configure_logging
from app.models import load_all_models
from app.scripts.seed import _ensure_user
from app.users.models import Role, User

logger = logging.getLogger("create_superadmin")


def _password() -> str:
    password = os.environ.get("SUPERADMIN_PASSWORD") or getpass.getpass("Super-admin password: ")
    if len(password) < PasswordPolicy.MIN:
        raise ValueError(f"the password needs at least {PasswordPolicy.MIN} characters")
    return PasswordPolicy.check(password)


async def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    load_all_models()
    email = os.environ.get("SUPERADMIN_EMAIL", "").strip().lower()
    first = os.environ.get("SUPERADMIN_FIRST_NAME", "").strip()
    last = os.environ.get("SUPERADMIN_LAST_NAME", "").strip()
    if not (email and first and last):
        logger.error("SUPERADMIN_EMAIL, SUPERADMIN_FIRST_NAME and SUPERADMIN_LAST_NAME are required")
        return 1
    try:
        password = _password()
    except ValueError as exc:
        logger.error("Invalid password: %s", exc)
        return 1
    engine = create_engine(settings.database_url, null_pool=True)
    try:
        async with create_sessionmaker(engine)() as db:
            if await db.scalar(select(User.id).where(User.email == email)):
                logger.error("An account already exists for %s", email)
                return 1
            await _ensure_user(db, email, Role.SUPER_ADMIN, first, last, password)
            await db.commit()
    finally:
        await engine.dispose()
    logger.info("Super-admin %s created", email)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
