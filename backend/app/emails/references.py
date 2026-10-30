"""Reply / forward recognition and request references (REQ-YYYY-NNNNNN) in subjects and bodies."""

import re

REFERENCE_RE = re.compile(r"\bREQ-\d{4}-\d{6}\b")
# Repeated reply / forward prefixes, in the languages of the app: "Re:", "RE[2]:", "Fwd:", "TR:", "رد:".
_PREFIX_RE = re.compile(
    r"^\s*((re|aw|fw|fwd|tr|ref|réf|رد|إعادة توجيه)\s*(\[\d+\])?\s*[:：]\s*)+", re.IGNORECASE
)
_REPLY_RE = re.compile(r"^\s*(re|aw|رد)\b", re.IGNORECASE)
_FORWARD_RE = re.compile(r"^\s*(fw|fwd|tr|إعادة توجيه)\b", re.IGNORECASE)
# Start of a quoted previous message: what follows is not the sender's own text.
_QUOTE_HEADER_RE = re.compile(
    r"^\s*(-{2,}\s*(original message|message d'origine|forwarded message|message transféré)\s*-{2,}"
    r"|on .{1,200} wrote:|le .{1,200} a écrit\s?:|من:|from:\s.+|de\s?:\s.+)\s*$",
    re.IGNORECASE,
)


def normalize_subject(subject: str) -> tuple[str, bool, bool]:
    """(subject without prefixes, is_reply, is_forward). The original subject is kept elsewhere."""
    is_reply = bool(_REPLY_RE.match(subject)) and bool(_PREFIX_RE.match(subject))
    is_forward = bool(_FORWARD_RE.match(subject)) and bool(_PREFIX_RE.match(subject))
    return _PREFIX_RE.sub("", subject).strip(), is_reply, is_forward


def own_text(body: str) -> str:
    """The sender's own lines: quoted lines ("> …") and everything after a quote header are dropped."""
    lines = []
    for line in body.splitlines():
        if _QUOTE_HEADER_RE.match(line):
            break
        if line.lstrip().startswith(">"):
            continue
        lines.append(line)
    return "\n".join(lines)


def find_reference(subject: str, body: str) -> str | None:
    """First reference in the subject, else in the sender's own text (never in quoted history)."""
    for text in (subject, own_text(body)):
        match = REFERENCE_RE.search(text or "")
        if match:
            return match.group(0)
    return None
