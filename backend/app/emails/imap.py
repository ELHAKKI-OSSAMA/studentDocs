"""IMAP provider (stdlib imaplib): one short read-only connection per poll.

- TLS with certificate verification (IMAP_SSL=true; plain IMAP only for local test servers);
- socket timeout on every operation;
- the folder is SELECTed read-only and bodies are fetched with BODY.PEEK[]: nothing is marked, moved or
  deleted on the server (people may read the same mailbox);
- errors are mapped to MailboxError codes; the connection is always logged out.
"""

import imaplib
import re
import ssl
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from app.emails.provider import MailboxError, MessageInfo

_SIZE_RE = re.compile(rb"RFC822\.SIZE (\d+)")
_FLAGS_RE = re.compile(rb"FLAGS \(([^)]*)\)")
_DATE_RE = re.compile(rb'INTERNALDATE "([^"]+)"')


@contextmanager
def _imap_errors(during_connect: bool = False) -> Iterator[None]:
    """Maps socket / protocol errors of IMAP calls (only) to MailboxError codes."""
    try:
        yield
    except MailboxError:
        raise
    except TimeoutError as exc:
        raise MailboxError("timeout") from exc
    except ssl.SSLError as exc:
        raise MailboxError("tls_error") from exc
    except imaplib.IMAP4.abort as exc:
        raise MailboxError("connection_lost") from exc
    except imaplib.IMAP4.error as exc:
        raise MailboxError("protocol_error") from exc
    except OSError as exc:
        raise MailboxError("connection_failed" if during_connect else "connection_lost") from exc


def _check(typ: str, what: str) -> None:
    if typ != "OK":
        raise MailboxError(f"{what}_failed")


def _literal(data: list) -> bytes | None:
    for item in data or []:
        if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], bytes):
            return item[1]
    return None


class ImapSession:
    def __init__(self, conn: imaplib.IMAP4, uid_validity: int) -> None:
        self._conn = conn
        self._uid_validity = uid_validity

    @property
    def uid_validity(self) -> int:
        return self._uid_validity

    def uids_after(self, uid: int) -> list[int]:
        with _imap_errors():
            typ, data = self._conn.uid("SEARCH", None, f"UID {uid + 1}:*")
        _check(typ, "search")
        found = [int(x) for x in (data[0] or b"").split()] if data else []
        # "n:*" always matches the last message, even when its UID is lower than n.
        return sorted(u for u in found if u > uid)

    def info(self, uid: int) -> MessageInfo | None:
        with _imap_errors():
            typ, data = self._conn.uid("FETCH", str(uid), "(RFC822.SIZE INTERNALDATE FLAGS)")
        _check(typ, "fetch")
        line = b" ".join(x if isinstance(x, bytes) else x[0] for x in data if x)
        size = _SIZE_RE.search(line)
        if size is None:
            return None  # expunged meanwhile
        internal = None
        if date := _DATE_RE.search(line):
            parsed = imaplib.Internaldate2tuple(b'INTERNALDATE "' + date.group(1) + b'"')
            if parsed:
                internal = datetime(*parsed[:6], tzinfo=UTC)
        flags = _FLAGS_RE.search(line)
        names = tuple(f.decode("ascii", "replace") for f in flags.group(1).split()) if flags else ()
        return MessageInfo(uid=uid, size=int(size.group(1)), internal_date=internal, flags=names[:20])

    def fetch(self, uid: int) -> bytes | None:
        with _imap_errors():
            typ, data = self._conn.uid("FETCH", str(uid), "(BODY.PEEK[])")
        _check(typ, "fetch")
        return _literal(data)

    def fetch_header(self, uid: int) -> bytes | None:
        with _imap_errors():
            typ, data = self._conn.uid("FETCH", str(uid), "(BODY.PEEK[HEADER])")
        _check(typ, "fetch")
        return _literal(data)


@dataclass(frozen=True)
class ImapProvider:
    host: str
    port: int
    username: str
    password: str
    folder: str = "INBOX"
    use_ssl: bool = True
    timeout: float = 30.0
    name: str = "imap"

    def _connect(self) -> imaplib.IMAP4:
        if self.use_ssl:
            return imaplib.IMAP4_SSL(
                self.host, self.port, ssl_context=ssl.create_default_context(), timeout=self.timeout
            )
        return imaplib.IMAP4(self.host, self.port, timeout=self.timeout)

    @contextmanager
    def session(self) -> Iterator[ImapSession]:
        with _imap_errors(during_connect=True):
            conn = self._connect()
        try:
            try:
                conn.login(self.username, self.password)
            except imaplib.IMAP4.error as exc:
                raise MailboxError("auth_failed") from exc
            with _imap_errors():
                typ, _ = conn.select(self._quoted_folder(), readonly=True)
                _check(typ, "select")
                _, values = conn.response("UIDVALIDITY")
            if not values or values[0] is None:
                raise MailboxError("no_uidvalidity")
            # Errors raised by the caller's own code (storage, database) propagate unchanged.
            yield ImapSession(conn, int(values[-1]))
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: S110 - best effort, the socket is closed anyway
                pass

    def _quoted_folder(self) -> str:
        return '"' + self.folder.replace("\\", "\\\\").replace('"', '\\"') + '"'
