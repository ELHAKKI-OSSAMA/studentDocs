"""Bounded MIME parsing of a raw message (stdlib `email`, policy.default).

Nothing here is trusted: headers are cleaned, charsets decoded with replacement, the MIME tree is bounded
(number of parts, depth) and attachments are only collected as bytes, to be validated by the Phase 3
pipeline (`validate_stream`) and scanned by ClamAV before anyone can download them.
"""

import email
import email.utils
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage, Message

from app.emails.sanitize import clean_header, clean_text, html_to_text, sanitize_html

MAX_PARTS = 200
MAX_DEPTH = 10
_ADDRESS_RE = re.compile(r"^[^@\s<>\"']{1,64}@[^@\s<>\"']{1,255}$")


class EmailParseError(Exception):
    """The message cannot be parsed at all (the case becomes FAILED / parse_error)."""


@dataclass
class ParsedAttachment:
    filename: str | None  # as sent (untrusted; validate_stream normalizes it)
    declared_type: str
    data: bytes


@dataclass
class ParsedEmail:
    message_id: str | None
    in_reply_to: str | None
    references: str | None
    from_address: str
    from_name: str | None
    to: list[str]
    cc: list[str]
    subject: str
    sent_at: datetime | None
    body_text: str
    body_html: str | None  # sanitized (nh3), never the original
    attachments: list[ParsedAttachment]
    auth_headers: list[str]
    auto_submitted: bool
    is_bounce: bool
    flags: dict = field(default_factory=dict)


def _header(msg: Message, name: str) -> str | None:
    try:
        value = msg.get(name)
    except Exception:  # malformed header that the policy cannot even represent
        return None
    return None if value is None else str(value)


def _addresses(msg: Message, name: str) -> list[tuple[str, str]]:
    try:
        values = msg.get_all(name) or []
        pairs = email.utils.getaddresses([str(v) for v in values])
    except Exception:
        return []
    out = []
    for display, addr in pairs:
        addr = addr.strip().lower()
        if _ADDRESS_RE.match(addr):
            out.append((clean_header(display, 255), addr))
    return out


def _decode(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if not isinstance(payload, bytes):
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:  # unknown charset name
        return payload.decode("latin-1", errors="replace")


def _message_id(value: str | None) -> str | None:
    value = clean_header(value, 998)
    return value or None


def _walk(msg: Message, depth: int, out: list[tuple[Message, int]], flags: dict) -> None:
    if len(out) >= MAX_PARTS:
        flags["mime_truncated"] = True
        return
    if depth > MAX_DEPTH:
        flags["mime_truncated"] = True
        return
    if msg.is_multipart():
        payload = msg.get_payload()
        for sub in payload if isinstance(payload, list) else []:
            _walk(sub, depth + 1, out, flags)
    else:
        out.append((msg, depth))


@dataclass
class Envelope:
    """Header fields stored with the raw message. Tolerant: a broken message still gets an envelope."""

    message_id: str | None
    in_reply_to: str | None
    references: str | None
    from_address: str
    from_name: str | None
    to: list[str]
    cc: list[str]
    subject: str
    sent_at: datetime | None
    auth_headers: list[str]


def _sent_at(msg: Message) -> datetime | None:
    date = _header(msg, "Date")
    if not date:
        return None
    try:
        value = email.utils.parsedate_to_datetime(date)
    except (TypeError, ValueError, IndexError):
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def parse_envelope(raw: bytes) -> Envelope:
    try:
        msg = email.message_from_bytes(raw, policy=policy.default)
    except Exception:
        msg = Message()
    senders = _addresses(msg, "From")
    from_name, from_address = senders[0] if senders else ("", "")
    try:
        auth_headers = [str(v) for v in (msg.get_all("Authentication-Results") or [])][:20]
    except Exception:
        auth_headers = []
    return Envelope(
        message_id=_message_id(_header(msg, "Message-ID")),
        in_reply_to=clean_header(_header(msg, "In-Reply-To"), 4000) or None,
        references=clean_header(_header(msg, "References"), 8000) or None,
        from_address=from_address,
        from_name=from_name or None,
        to=[a for _, a in _addresses(msg, "To")][:50],
        cc=[a for _, a in _addresses(msg, "Cc")][:50],
        subject=clean_header(_header(msg, "Subject")),
        sent_at=_sent_at(msg),
        auth_headers=auth_headers,
    )


def parse_message(raw: bytes, *, body_max_chars: int, html_max_bytes: int) -> ParsedEmail:
    try:
        msg: EmailMessage = email.message_from_bytes(raw, policy=policy.default)  # type: ignore[assignment]
    except Exception as exc:
        raise EmailParseError("unparseable message") from exc
    if not msg.keys():
        raise EmailParseError("no headers")

    flags: dict = {}
    senders = _addresses(msg, "From")
    if not senders:
        raise EmailParseError("no valid From address")
    from_name, from_address = senders[0]

    sent_at = _sent_at(msg)

    parts: list[tuple[Message, int]] = []
    _walk(msg, 0, parts, flags)
    text_plain: str | None = None
    html_raw: str | None = None
    attachments: list[ParsedAttachment] = []
    for part, _ in parts:
        content_type = part.get_content_type()
        disposition = (part.get_content_disposition() or "").lower()
        try:
            filename = part.get_filename()
        except Exception:
            filename = None
        if disposition == "attachment" or filename or not content_type.startswith("text/"):
            if content_type.startswith("multipart/") or content_type in ("message/delivery-status",):
                continue
            data = part.get_payload(decode=True)
            if isinstance(data, bytes) and data:
                attachments.append(ParsedAttachment(filename, content_type, data))
            continue
        if content_type == "text/plain" and text_plain is None:
            text_plain = _decode(part)
        elif content_type == "text/html" and html_raw is None:
            html_raw = _decode(part)

    body_html = None
    if html_raw is not None:
        body_html, html_truncated = sanitize_html(html_raw, html_max_bytes)
        if html_truncated:
            flags["html_truncated"] = True
    # An empty text/plain alternative next to an HTML body: the HTML text is used (never the raw HTML).
    if text_plain is not None and text_plain.strip():
        source = text_plain
    else:
        source = html_to_text(body_html) if body_html else (text_plain or "")
    body_text, text_truncated = clean_text(source, body_max_chars)
    if text_truncated:
        flags["body_truncated"] = True

    auto_submitted = (_header(msg, "Auto-Submitted") or "no").strip().lower() not in ("", "no")
    auto_submitted = auto_submitted or any(_header(msg, h) for h in ("X-Autoreply", "X-Autorespond"))
    auto_submitted = auto_submitted or (_header(msg, "Precedence") or "").strip().lower() == "auto_reply"
    report_type = (msg.get_param("report-type") or "") if msg.get_content_type() == "multipart/report" else ""
    is_bounce = str(report_type).lower() == "delivery-status" or from_address.startswith("mailer-daemon@")

    try:
        auth_headers = [str(v) for v in (msg.get_all("Authentication-Results") or [])]
    except Exception:
        auth_headers = []

    return ParsedEmail(
        message_id=_message_id(_header(msg, "Message-ID")),
        in_reply_to=clean_header(_header(msg, "In-Reply-To"), 4000) or None,
        references=clean_header(_header(msg, "References"), 8000) or None,
        from_address=from_address,
        from_name=from_name or None,
        to=[a for _, a in _addresses(msg, "To")][:50],
        cc=[a for _, a in _addresses(msg, "Cc")][:50],
        subject=clean_header(_header(msg, "Subject")),
        sent_at=sent_at,
        body_text=body_text,
        body_html=body_html,
        attachments=attachments,
        auth_headers=auth_headers[:20],
        auto_submitted=auto_submitted,
        is_bounce=is_bounce,
        flags=flags,
    )
