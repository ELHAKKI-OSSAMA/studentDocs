"""Request state machine: the single source of truth for allowed transitions.

Pure and side-effect free. `RequestActions` applies a transition (guards, history, audit, notifications).
"""

import enum
from dataclasses import dataclass

from app.auth.permissions import Perm
from app.requests.models import TERMINAL_STATUSES, RequestStatus

S = RequestStatus


class Actor(enum.StrEnum):
    SYSTEM = "SYSTEM"
    STUDENT = "STUDENT"  # the request owner
    STAFF = "STAFF"


@dataclass(frozen=True)
class Transition:
    sources: frozenset[RequestStatus]
    target: RequestStatus
    actor: Actor
    permission: Perm | None = None
    # A comment is mandatory (information request, rejection reason, staff cancellation reason).
    requires_comment: bool = False


def _t(sources, target, actor, permission=None, requires_comment=False) -> Transition:
    return Transition(frozenset(sources), target, actor, permission, requires_comment)


NON_TERMINAL = frozenset(s for s in RequestStatus if s not in TERMINAL_STATUSES)

TRANSITIONS: tuple[Transition, ...] = (
    _t({S.SUBMITTED}, S.RECEIVED, Actor.SYSTEM),
    _t({S.RECEIVED}, S.IN_REVIEW, Actor.STAFF, Perm.REQUESTS_PROCESS),
    _t({S.IN_REVIEW}, S.NEEDS_INFORMATION, Actor.STAFF, Perm.REQUESTS_PROCESS, requires_comment=True),
    # The student answers the information request (message + optional files) → back to review.
    _t({S.NEEDS_INFORMATION}, S.IN_REVIEW, Actor.STUDENT),
    _t({S.NEEDS_INFORMATION}, S.IN_REVIEW, Actor.STAFF, Perm.REQUESTS_PROCESS),
    _t({S.IN_REVIEW}, S.PROCESSING, Actor.STAFF, Perm.REQUESTS_PROCESS),
    _t({S.PROCESSING}, S.APPROVED, Actor.STAFF, Perm.REQUESTS_APPROVE),
    _t({S.APPROVED}, S.DOCUMENT_AVAILABLE, Actor.STAFF, Perm.REQUESTS_PROCESS),
    _t({S.APPROVED}, S.READY_FOR_PICKUP, Actor.STAFF, Perm.REQUESTS_PROCESS),
    _t({S.DOCUMENT_AVAILABLE, S.READY_FOR_PICKUP}, S.COMPLETED, Actor.STAFF, Perm.REQUESTS_PROCESS),
    _t(
        {S.RECEIVED, S.IN_REVIEW, S.NEEDS_INFORMATION, S.PROCESSING},
        S.REJECTED,
        Actor.STAFF,
        Perm.REQUESTS_REJECT,
        requires_comment=True,
    ),
    # Students may cancel only before the administration starts the review.
    _t({S.SUBMITTED, S.RECEIVED}, S.CANCELLED, Actor.STUDENT),
    _t(NON_TERMINAL, S.CANCELLED, Actor.STAFF, Perm.REQUESTS_PROCESS, requires_comment=True),
)


def find_transition(current: RequestStatus, target: RequestStatus, actor: Actor) -> Transition | None:
    for t in TRANSITIONS:
        if t.actor == actor and t.target == target and current in t.sources:
            return t
    return None


def allowed_targets(current: RequestStatus, actor: Actor, permissions: frozenset[str]) -> list[RequestStatus]:
    """Targets reachable by this actor (ignores data guards such as 'issued document uploaded')."""
    targets: list[RequestStatus] = []
    for t in TRANSITIONS:
        if t.actor != actor or current not in t.sources or t.target in targets:
            continue
        if t.permission is None or t.permission.value in permissions:
            targets.append(t.target)
    return targets
