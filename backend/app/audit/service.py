import ipaddress
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog


def _valid_ip(ip: str | None) -> str | None:
    try:
        return str(ipaddress.ip_address(ip)) if ip else None
    except ValueError:
        return None


def record(
    db: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    action: str,
    entity: str,
    entity_id: object,
    ip: str | None = None,
    details: dict | None = None,
) -> None:
    """Adds an audit entry to the current transaction (committed together with the audited change)."""
    db.add(
        AuditLog(
            actor_user_id=actor_id,
            action=action,
            entity=entity,
            entity_id=str(entity_id),
            ip=_valid_ip(ip),
            details=details,
        )
    )
