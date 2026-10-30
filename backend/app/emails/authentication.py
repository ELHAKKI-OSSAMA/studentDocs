"""Sender authentication, from the Authentication-Results headers (RFC 8601) present in the message.

StudentDocs does not verify SPF / DKIM / DMARC itself (IMAP gives the stored message, not the SMTP
session). It only reads what the receiving server recorded, and only from the servers listed in
EMAIL_TRUSTED_AUTHSERV_IDS: any other Authentication-Results header may have been written by the sender.

Verdicts:
- PASS: favorable and consistent (DMARC pass aligned with From, or aligned DKIM pass with no failure);
- FAIL: an explicit failure (DMARC fail, or only failing DKIM / SPF results);
- CONTRADICTORY: trusted results disagree (pass and fail, or DMARC for another domain than From);
- ABSENT: no trusted header (none at all, or none from a trusted server);
- INCONCLUSIVE: trusted header without a usable result (none, neutral, temperror, …).
Only PASS can turn a known sender address into an automatic student identification.
"""

import enum
import re

_COMMENT_RE = re.compile(r"\([^()]*\)")


class AuthVerdict(enum.StrEnum):
    PASS = "PASS"  # noqa: S105 - a verdict, not a password
    FAIL = "FAIL"
    CONTRADICTORY = "CONTRADICTORY"
    ABSENT = "ABSENT"
    INCONCLUSIVE = "INCONCLUSIVE"


def _strip_comments(value: str) -> str:
    previous = None
    while previous != value:
        previous, value = value, _COMMENT_RE.sub(" ", value)
    return value


def parse_header(value: str) -> tuple[str, list[dict]]:
    """(authserv-id, [{method, result, props}]) of one Authentication-Results header."""
    parts = [p.strip() for p in _strip_comments(value.replace("\n", " ")).split(";")]
    authserv = (parts[0].split() or [""])[0].lower() if parts else ""
    results = []
    for part in parts[1:]:
        tokens = part.split()
        if not tokens or "=" not in tokens[0]:
            continue
        method, _, result = tokens[0].partition("=")
        props = {}
        for token in tokens[1:]:
            key, sep, val = token.partition("=")
            if sep:
                props[key.lower()] = val.strip('"').lower()
        results.append({"method": method.lower(), "result": result.lower(), "props": props})
    return authserv, results


def _domain(value: str) -> str:
    return value.rsplit("@", 1)[-1].strip().lower().rstrip(".")


def _aligned(domain: str, from_domain: str) -> bool:
    # Relaxed alignment: same organizational domain or a subdomain of the From domain.
    return bool(domain) and (domain == from_domain or domain.endswith("." + from_domain))


def evaluate(headers: list[str], from_address: str, trusted_ids: list[str]) -> dict:
    trusted = {t.strip().lower() for t in trusted_ids if t.strip()}
    from_domain = _domain(from_address)
    results: list[dict] = []
    used = ignored = 0
    for header in headers:
        authserv, parsed = parse_header(header)
        if authserv in trusted:
            used += 1
            results.extend(parsed)
        else:
            ignored += 1

    def of(method: str) -> list[dict]:
        return [r for r in results if r["method"] == method]

    dmarc, dkim, spf = of("dmarc"), of("dkim"), of("spf")
    summary = {
        "trusted_headers": used,
        "ignored_headers": ignored,
        "dmarc": sorted({r["result"] for r in dmarc}),
        "dkim": sorted({r["result"] for r in dkim}),
        "spf": sorted({r["result"] for r in spf}),
    }
    if not used:
        return {"verdict": AuthVerdict.ABSENT.value, **summary}

    failing = {"fail", "permerror", "softfail"}
    dmarc_pass = [r for r in dmarc if r["result"] == "pass"]
    dmarc_fail = [r for r in dmarc if r["result"] in failing]
    dkim_pass = [r for r in dkim if r["result"] == "pass"]
    dkim_fail = [r for r in dkim if r["result"] in failing]
    spf_pass = [r for r in spf if r["result"] == "pass"]
    spf_fail = [r for r in spf if r["result"] in failing]

    if dmarc_pass and dmarc_fail:
        verdict = AuthVerdict.CONTRADICTORY
    elif dmarc_fail:
        verdict = AuthVerdict.FAIL
    elif dmarc_pass:
        other_domain = any(
            r["props"].get("header.from") and _domain(r["props"]["header.from"]) != from_domain
            for r in dmarc_pass
        )
        all_mechanisms_fail = (dkim or spf) and not dkim_pass and not spf_pass and (dkim_fail or spf_fail)
        verdict = AuthVerdict.CONTRADICTORY if other_domain or all_mechanisms_fail else AuthVerdict.PASS
    else:
        aligned_dkim = [
            r
            for r in dkim_pass
            if _aligned(_domain(r["props"].get("header.d") or r["props"].get("header.i", "")), from_domain)
        ]
        if aligned_dkim and (dkim_fail or spf_fail):
            verdict = AuthVerdict.CONTRADICTORY
        elif aligned_dkim:
            verdict = AuthVerdict.PASS
        elif (dkim_fail or spf_fail) and not (dkim_pass or spf_pass):
            verdict = AuthVerdict.FAIL
        else:
            verdict = AuthVerdict.INCONCLUSIVE
    return {"verdict": verdict.value, **summary}
