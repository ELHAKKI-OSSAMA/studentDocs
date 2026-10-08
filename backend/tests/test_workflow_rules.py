"""Pure unit tests of the state machine and upload validation (no I/O)."""

import pytest

from app.core.errors import AppError
from app.documents.validation import safe_filename, sniff_mime, validate_upload
from app.requests.models import RequestStatus as S
from app.requests.workflow import TRANSITIONS, Actor, allowed_targets, find_transition

ALL_STAFF = frozenset(
    {"requests.process", "requests.approve", "requests.reject", "requests.assign", "requests.read"}
)


def test_main_path_and_pickup_path_are_allowed_for_staff():
    path = [S.RECEIVED, S.IN_REVIEW, S.PROCESSING, S.APPROVED, S.DOCUMENT_AVAILABLE, S.COMPLETED]
    for current, target in zip(path, path[1:], strict=False):
        assert find_transition(current, target, Actor.STAFF), (current, target)
    assert find_transition(S.APPROVED, S.READY_FOR_PICKUP, Actor.STAFF)
    assert find_transition(S.READY_FOR_PICKUP, S.COMPLETED, Actor.STAFF)
    assert find_transition(S.SUBMITTED, S.RECEIVED, Actor.SYSTEM)


def test_information_loop():
    assert find_transition(S.IN_REVIEW, S.NEEDS_INFORMATION, Actor.STAFF).requires_comment
    assert find_transition(S.NEEDS_INFORMATION, S.IN_REVIEW, Actor.STUDENT)
    assert find_transition(S.NEEDS_INFORMATION, S.IN_REVIEW, Actor.STAFF)


@pytest.mark.parametrize("actor", list(Actor))
def test_no_shortcut_to_the_end(actor):
    for start in (S.SUBMITTED, S.RECEIVED, S.IN_REVIEW, S.PROCESSING):
        assert find_transition(start, S.COMPLETED, actor) is None
    assert find_transition(S.RECEIVED, S.APPROVED, actor) is None
    assert find_transition(S.IN_REVIEW, S.DOCUMENT_AVAILABLE, actor) is None


def test_student_can_only_cancel_before_review():
    assert find_transition(S.SUBMITTED, S.CANCELLED, Actor.STUDENT)
    assert find_transition(S.RECEIVED, S.CANCELLED, Actor.STUDENT)
    for status in (S.IN_REVIEW, S.NEEDS_INFORMATION, S.PROCESSING, S.APPROVED, S.COMPLETED):
        assert find_transition(status, S.CANCELLED, Actor.STUDENT) is None
    # Apart from cancelling and answering an information request, students drive nothing.
    student_targets = {t.target for t in TRANSITIONS if t.actor == Actor.STUDENT}
    assert student_targets == {S.CANCELLED, S.IN_REVIEW}


def test_terminal_states_have_no_exit():
    for terminal in (S.COMPLETED, S.REJECTED, S.CANCELLED):
        for actor in Actor:
            assert allowed_targets(terminal, actor, ALL_STAFF) == []


def test_rejection_requires_reason_and_permission():
    t = find_transition(S.PROCESSING, S.REJECTED, Actor.STAFF)
    assert t.requires_comment and t.permission.value == "requests.reject"
    assert find_transition(S.APPROVED, S.REJECTED, Actor.STAFF) is None
    assert S.APPROVED not in allowed_targets(S.PROCESSING, Actor.STAFF, ALL_STAFF - {"requests.approve"})
    assert S.APPROVED in allowed_targets(S.PROCESSING, Actor.STAFF, ALL_STAFF)


# --- uploads ------------------------------------------------------------------------------------------


def test_sniffing_uses_content_not_name():
    assert sniff_mime(b"%PDF-1.7 ...") == ("application/pdf", ".pdf")
    assert sniff_mime(b"\x89PNG\r\n\x1a\n...") == ("image/png", ".png")
    assert sniff_mime(b"\xff\xd8\xff\xe0...") == ("image/jpeg", ".jpg")
    assert sniff_mime(b"MZ\x90\x00 executable") is None
    assert sniff_mime(b"<html><script>") is None


@pytest.mark.parametrize(
    ("original", "expected"),
    [
        ("../../etc/passwd.pdf", "passwd.pdf"),
        ("C:\\Users\\x\\carte.pdf", "carte.pdf"),
        ("relevé de notes.pdf", "relevé_de_notes.pdf"),
        ("<script>alert(1)</script>.pdf", "script.pdf"),  # "/" splits the path
        ("evil.exe", "evil.pdf"),  # extension always follows the real content type
        ("", "document.pdf"),
        ("\x00\x1f.pdf", "document.pdf"),
        ("a" * 300 + ".pdf", "a" * 100 + ".pdf"),
    ],
)
def test_safe_filename(original, expected):
    assert safe_filename(original, ".pdf") == expected


def test_validate_upload_rejections():
    with pytest.raises(AppError) as empty:
        validate_upload("x.pdf", b"", 100)
    assert empty.value.code == "file_empty"
    with pytest.raises(AppError) as big:
        validate_upload("x.pdf", b"%PDF-" + b"0" * 200, 100)
    assert big.value.code == "file_too_large"
    with pytest.raises(AppError) as exe:
        validate_upload("cv.pdf", b"MZ\x90\x00", 100)
    assert exe.value.code == "file_type_not_allowed"
    ok = validate_upload("cin.PDF", b"%PDF-1.4", 100)
    assert ok.mime_type == "application/pdf" and ok.filename == "cin.pdf" and len(ok.sha256) == 64
