"""Deterministic student identification. The AI never sets `student_id`.

Rule 1 (the only automatic one): the sender address is the verified address of an active student AND
the trusted Authentication-Results verdict is PASS. Anything weaker (no / failing / contradictory
authentication, a student number or a reference quoted in the text, a name) only produces candidates
with their evidence; a staff member decides.
"""

import re
import unicodedata
import uuid
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.emails.authentication import AuthVerdict
from app.emails.models import IdentificationMethod
from app.requests.models import Request
from app.students.models import Student
from app.users.models import AllowedEmailDomain, Role, User

# Institutional numbers (CNE / Apogée): optional letters then 6 to 12 digits, e.g. D130000001.
STUDENT_NUMBER_RE = re.compile(r"\b[A-Za-z]{0,2}\d{6,12}\b")
SCORES = {
    "sender_email_authenticated": 100,
    "sender_email": 60,
    "student_number": 50,
    "request_reference": 40,
    "name_match": 20,
}
MAX_CANDIDATES = 5


@dataclass
class Identification:
    student_id: uuid.UUID | None = None
    method: IdentificationMethod | None = None
    candidates: list[dict] = field(default_factory=list)


def _norm_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(c for c in value if not unicodedata.combining(c)).lower()
    return " ".join(re.findall(r"\w+", value))


class _Candidates:
    def __init__(self) -> None:
        self.by_student: dict[uuid.UUID, dict] = {}

    def add(self, student_id: uuid.UUID, reason: str, **evidence) -> None:
        entry = self.by_student.setdefault(
            student_id, {"student_id": str(student_id), "reasons": [], "score": 0}
        )
        if reason not in entry["reasons"]:
            entry["reasons"].append(reason)
            entry["score"] = min(100, entry["score"] + SCORES[reason])
        for key, value in evidence.items():
            entry.setdefault("evidence", {})[key] = value

    def ranked(self) -> list[dict]:
        return sorted(self.by_student.values(), key=lambda c: -c["score"])[:MAX_CANDIDATES]


async def identify(
    db: AsyncSession,
    *,
    from_address: str,
    from_name: str | None,
    auth_verdict: str,
    own_text: str,
    reference_request: Request | None,
    extra_student_numbers: list[str] | None = None,
) -> Identification:
    result = Identification()
    candidates = _Candidates()

    sender = await db.scalar(
        select(Student)
        .join(User, Student.user_id == User.id)
        .where(User.email == from_address, User.role == Role.STUDENT, User.is_active.is_(True))
    )
    if sender is not None:
        verified = sender.user.email_verified_at is not None
        if auth_verdict == AuthVerdict.PASS and verified:
            domain = from_address.rsplit("@", 1)[-1]
            institutional = await db.scalar(
                select(AllowedEmailDomain.id).where(
                    AllowedEmailDomain.domain == domain, AllowedEmailDomain.is_active.is_(True)
                )
            )
            result.student_id = sender.id
            result.method = (
                IdentificationMethod.INSTITUTIONAL_EMAIL
                if institutional
                else IdentificationMethod.KNOWN_EMAIL
            )
            candidates.add(sender.id, "sender_email_authenticated", authentication=auth_verdict)
        else:
            candidates.add(sender.id, "sender_email", authentication=auth_verdict, address_verified=verified)

    numbers = {m.group(0).upper() for m in STUDENT_NUMBER_RE.finditer(own_text or "")}
    numbers |= {n.strip().upper() for n in extra_student_numbers or [] if n and n.strip()}
    if numbers:
        rows = await db.scalars(select(Student).where(func.upper(Student.student_number).in_(numbers)))
        for student in rows.all():
            candidates.add(student.id, "student_number", student_number=student.student_number)

    if reference_request is not None:
        candidates.add(
            reference_request.student_id, "request_reference", reference=reference_request.reference
        )

    wanted = _norm_name(from_name or "")
    if wanted and len(wanted.split()) >= 2:
        rows = await db.scalars(
            select(Student)
            .join(User, Student.user_id == User.id)
            .where(
                User.role == Role.STUDENT,
                func.lower(func.concat(User.first_name, " ", User.last_name)) == wanted,
            )
            .limit(2)
        )
        same_name = rows.all()
        if len(same_name) == 1:  # homonyms prove nothing
            candidates.add(same_name[0].id, "name_match")

    result.candidates = candidates.ranked()
    return result
