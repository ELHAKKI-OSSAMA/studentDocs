"""The standard EICAR antivirus test file (harmless by design, detected by every antivirus).

It is assembled at runtime so that no file in the repository contains the signature (host antivirus
software would otherwise quarantine the source file). Never replace this with real malware.
"""

_PARTS = (
    r"X5O!P%@AP[4\PZX54(P^)7CC)7}",
    "$EICAR-STANDARD-",
    "ANTIVIRUS-TEST-",
    "FILE!$H+H*",
)


def eicar() -> bytes:
    return "".join(_PARTS).encode("ascii")


def eicar_pdf() -> bytes:
    """A structurally valid PDF whose content stream is the EICAR test string.

    It passes the format validation (real PDF magic bytes) and ClamAV must still flag it: this exercises
    the antivirus itself, not the type filter.
    """
    stream = eicar()
    return (
        b"%PDF-1.4\n1 0 obj\n<< /Length "
        + str(len(stream)).encode()
        + b" >>\nstream\n"
        + stream
        + b"\nendstream\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"
    )
