"""Antivirus scanning through the ClamAV daemon (clamd), INSTREAM command over TCP.

Protocol (clamd(8)): send `zINSTREAM\\0`, then chunks prefixed with their length as a 4-byte big-endian
integer, then a zero-length chunk. clamd answers `stream: OK`, `stream: <signature> FOUND` or
`<reason> ERROR` (e.g. `INSTREAM size limit exceeded. ERROR`).

Only an explicit `OK` is CLEAN. Anything else is INFECTED or an exception: callers fail closed.
"""

import socket
import struct
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

MAX_CHUNK = 64 * 1024


class ScannerUnavailable(Exception):
    """The scanner cannot be reached or timed out: transient, the scan may be retried."""


class ScannerError(Exception):
    """The scanner answered but could not scan the file (size limit, unreadable stream, …)."""


@dataclass(frozen=True)
class ScanResult:
    infected: bool
    signature: str | None = None


class Scanner(Protocol):
    def scan(self, chunks: Iterable[bytes]) -> ScanResult: ...

    def ping(self) -> bool: ...


@dataclass(frozen=True)
class ClamdScanner:
    host: str
    port: int
    timeout: float = 60.0

    def _connect(self) -> socket.socket:
        try:
            return socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as exc:  # refused, unknown host, timeout
            raise ScannerUnavailable(f"clamd unreachable at {self.host}:{self.port}") from exc

    @staticmethod
    def _read_reply(sock: socket.socket) -> str:
        data = b""
        while not data.endswith(b"\0"):
            part = sock.recv(4096)
            if not part:
                break
            data += part
        return data.rstrip(b"\0").decode("utf-8", "replace").strip()

    def ping(self) -> bool:
        with self._connect() as sock:
            try:
                sock.sendall(b"zPING\0")
                return self._read_reply(sock) == "PONG"
            except OSError as exc:
                raise ScannerUnavailable("clamd did not answer PING") from exc

    def scan(self, chunks: Iterable[bytes]) -> ScanResult:
        with self._connect() as sock:
            try:
                sock.sendall(b"zINSTREAM\0")
                for chunk in chunks:
                    for start in range(0, len(chunk), MAX_CHUNK):
                        part = chunk[start : start + MAX_CHUNK]
                        sock.sendall(struct.pack("!L", len(part)) + part)
                sock.sendall(struct.pack("!L", 0))
                reply = self._read_reply(sock)
            except (TimeoutError, ConnectionError) as exc:
                raise ScannerUnavailable("clamd connection lost or timed out") from exc
            except OSError as exc:
                # clamd closes the socket when a size limit is hit: an answer may still be readable.
                try:
                    reply = self._read_reply(sock)
                except OSError:
                    raise ScannerUnavailable("clamd connection failed") from exc
        return self.parse_reply(reply)

    @staticmethod
    def parse_reply(reply: str) -> ScanResult:
        body = reply.split(":", 1)[1].strip() if reply.startswith("stream:") else reply
        if body == "OK":
            return ScanResult(infected=False)
        if body.endswith(" FOUND"):
            return ScanResult(infected=True, signature=body[: -len(" FOUND")].strip()[:200] or "unknown")
        raise ScannerError(f"clamd could not scan the file: {reply[:200] or 'empty reply'}")
