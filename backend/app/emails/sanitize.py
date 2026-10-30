"""Untrusted email content → safe text and safe HTML.

- The original HTML is never stored for display nor sent to the browser: only `sanitize_html` output,
  which is additionally rendered in a sandboxed iframe (no scripts, no origin) by the frontend.
- `sanitize_html` uses nh3 (ammonia) with a strict allow-list: no script/style/iframe/form/svg/math/img,
  no style/class/on* attributes, links limited to http(s)/mailto with rel=noopener noreferrer nofollow.
  Images are dropped entirely (tracking pixels, remote content).
- `clean_text` normalizes Unicode, removes control and bidi-override characters and bounds the length.
"""

import re
import unicodedata
from html import unescape
from html.parser import HTMLParser

import nh3

ALLOWED_TAGS = {
    "p", "br", "div", "span", "b", "strong", "i", "em", "u", "s", "small", "sub", "sup",
    "ul", "ol", "li", "blockquote", "pre", "code", "hr",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "table", "thead", "tbody", "tfoot", "tr", "td", "th", "caption",
    "a",
}  # fmt: skip
ALLOWED_ATTRIBUTES = {"a": {"href", "title"}, "td": {"colspan", "rowspan"}, "th": {"colspan", "rowspan"}}
URL_SCHEMES = {"http", "https", "mailto"}
# Tags whose content is dropped too (not just the tag).
DROPPED_CONTENT_TAGS = {
    "script",
    "style",
    "head",
    "title",
    "template",
    "noscript",
    "object",
    "embed",
    "svg",
    "math",
}

# Control characters except tab / newline, and bidi embedding / override / isolate controls (spoofing).
_BIDI = "‪‫‬‭‮⁦⁧⁨⁩"
_BLOCK_TAGS = {
    "p", "div", "br", "li", "tr", "table", "blockquote", "pre", "hr",
    "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol",
}  # fmt: skip


def strip_controls(text: str) -> str:
    out = []
    for ch in text:
        if ch in "\n\t":
            out.append(ch)
        elif ch in _BIDI:
            continue
        elif unicodedata.category(ch) in ("Cc", "Cs", "Co", "Cn"):
            continue
        else:
            out.append(ch)
    return "".join(out)


def clean_text(text: str, max_chars: int) -> tuple[str, bool]:
    """Normalized, bounded plain text. Returns (text, truncated)."""
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    text = strip_controls(text).replace("\t", " ")
    text = re.sub(r"[  ]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > max_chars:
        return text[:max_chars], True
    return text, False


def clean_header(value: str | None, max_chars: int = 998) -> str:
    """One-line header value (subject, display name): no control characters, collapsed whitespace."""
    text = strip_controls(unicodedata.normalize("NFC", value or "")).replace("\n", " ").replace("\t", " ")
    return re.sub(r"\s+", " ", text).strip()[:max_chars]


def sanitize_html(html: str, max_bytes: int) -> tuple[str, bool]:
    """Allow-listed HTML (display only). Returns (html, truncated). Oversized input is cut before parsing."""
    truncated = False
    if len(html.encode("utf-8", "replace")) > max_bytes:
        html = html.encode("utf-8", "replace")[:max_bytes].decode("utf-8", "ignore")
        truncated = True
    html = strip_controls(html)
    cleaned = nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        clean_content_tags=DROPPED_CONTENT_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=URL_SCHEMES,
        link_rel="noopener noreferrer nofollow",
        strip_comments=True,
    )
    return cleaned, truncated


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def html_to_text(sanitized_html: str) -> str:
    """Plain text of already sanitized HTML (used when a message has no text/plain part)."""
    parser = _TextExtractor()
    parser.feed(sanitized_html)
    parser.close()
    text = unescape("".join(parser.parts))
    return re.sub(r"[ \t]+", " ", text)
