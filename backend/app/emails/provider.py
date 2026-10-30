"""Mailbox access abstraction. IMAP is the only implementation (MS Graph / Gmail API can plug in later)."""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class MailboxError(Exception):
    """Mailbox unreachable or refusing us. `code` is safe to store (never server output or secrets)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class MessageInfo:
    uid: int
    size: int
    internal_date: datetime | None
    flags: tuple[str, ...]


class MailboxSession(Protocol):
    @property
    def uid_validity(self) -> int: ...

    def uids_after(self, uid: int) -> list[int]:
        """UIDs strictly greater than `uid`, ascending."""
        ...

    def info(self, uid: int) -> MessageInfo | None: ...

    def fetch(self, uid: int) -> bytes | None:
        """The full raw message, without changing its flags (no \\Seen)."""
        ...

    def fetch_header(self, uid: int) -> bytes | None: ...


class EmailProvider(Protocol):
    name: str

    def session(self) -> AbstractContextManager[MailboxSession]:
        """Read-only session on the configured folder, always closed on exit."""
        ...
