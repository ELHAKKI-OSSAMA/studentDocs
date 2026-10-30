"""Sends a test email to GreenMail by SMTP (used by the E2E suite through `docker compose exec`).

    python -m tests.support.send_email --to scolarite@univ-demo.ma < message.json

The JSON on stdin describes the message: from, subject, body, optional html, auth (an
Authentication-Results header value), headers, and attachments [{filename, content_type, base64}].
The EICAR test file is never stored anywhere: `{"eicar_pdf": true}` assembles it at runtime.
"""

import argparse
import base64
import json
import os
import smtplib
import sys
from email.message import EmailMessage
from email.utils import make_msgid


def _eicar_pdf() -> bytes:
    from tests.eicar import eicar_pdf

    return eicar_pdf()


def build(spec: dict, to: str) -> bytes:
    msg = EmailMessage()
    if spec.get("auth"):
        msg["Authentication-Results"] = spec["auth"]
    msg["From"] = spec["from"]
    msg["To"] = to
    msg["Subject"] = spec.get("subject", "")
    msg["Message-ID"] = make_msgid(domain="e2e.test")
    for key, value in (spec.get("headers") or {}).items():
        msg[key] = value
    # base64: GreenMail does not undo SMTP dot-stuffing of quoted-printable lines starting with ".".
    msg.set_content(spec.get("body", ""), cte="base64")
    if spec.get("html"):
        msg.add_alternative(spec["html"], subtype="html", cte="base64")
    for att in spec.get("attachments") or []:
        data = _eicar_pdf() if att.get("eicar_pdf") else base64.b64decode(att["base64"])
        maintype, subtype = att.get("content_type", "application/pdf").split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=att["filename"])
    return msg.as_bytes()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--to", required=True)
    args = parser.parse_args()
    spec = json.load(sys.stdin)
    host = os.environ.get("GREENMAIL_HOST", "greenmail")
    with smtplib.SMTP(host, 3025, timeout=10) as smtp:
        smtp.sendmail("e2e@e2e.test", [args.to], build(spec, args.to))


if __name__ == "__main__":
    main()
