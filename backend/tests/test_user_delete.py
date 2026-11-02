"""Super-admin deletes accounts without history; accounts with history can only be deactivated."""

import uuid

from sqlalchemy import select

from app.audit.models import AuditLog
from app.students.models import Student
from app.users.models import Role, User
from tests.conftest import csrf
from tests.factories import make_catalog, make_enrollment, submit


def _path(user_id) -> str:
    return f"/api/v1/admin/users/{user_id}"


async def test_delete_account_without_history(harness):
    superadmin, me = await harness.logged_in(Role.SUPER_ADMIN)
    admin, _ = await harness.logged_in(Role.ADMIN)
    student = await harness.create_user(Role.STUDENT, verified=False)
    async with superadmin, admin:
        # An administrator without users.manage cannot delete.
        assert (await admin.delete(_path(student.id), headers=csrf(admin))).status_code == 403
        res = await superadmin.delete(_path(student.id), headers=csrf(superadmin))
        assert res.status_code == 204, res.text
        assert (await superadmin.delete(_path(student.id), headers=csrf(superadmin))).status_code == 404
        # Never yourself.
        res = await superadmin.delete(_path(me.id), headers=csrf(superadmin))
        assert res.status_code == 422 and res.json()["error"]["code"] == "cannot_modify_self"
        assert (await superadmin.delete(_path(uuid.uuid4()), headers=csrf(superadmin))).status_code == 404

    async with harness.app.state.sessionmaker() as db:
        assert await db.get(User, student.id) is None
        # The student profile goes with it (ON DELETE CASCADE).
        assert await db.scalar(select(Student).where(Student.user_id == student.id)) is None
        entry = await db.scalar(
            select(AuditLog).where(AuditLog.action == "USER_DELETED", AuditLog.entity_id == str(student.id))
        )
        assert entry.actor_user_id == me.id and entry.details["email"] == student.email


async def test_account_with_history_cannot_be_deleted(harness):
    catalog = await make_catalog(harness)
    student, user = await harness.logged_in()
    enrollment = await make_enrollment(harness, user, catalog)
    superadmin, _ = await harness.logged_in(Role.SUPER_ADMIN)
    async with student, superadmin:
        assert (await submit(student, enrollment.id, [(catalog.digital, 1)])).status_code == 201
        res = await superadmin.delete(_path(user.id), headers=csrf(superadmin))
        assert res.status_code == 409 and res.json()["error"]["code"] == "user_has_history"
    async with harness.app.state.sessionmaker() as db:
        assert await db.get(User, user.id) is not None
