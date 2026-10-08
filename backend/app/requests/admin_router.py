"""Staff request endpoints.

Each action requires its own permission; transitions always go through the state machine.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import select

from app.auth.dependencies import Requires
from app.auth.permissions import Perm
from app.core.crud import Page, PageParams
from app.core.deps import ClientIp, DbSession, DocumentsDep, SettingsDep, StorageDep
from app.core.errors import AppError
from app.documents.service import download_response, find_document
from app.documents.upload import parse_multipart
from app.messages.models import AuthorSide
from app.messages.service import thread
from app.requests.actions import RequestActions
from app.requests.models import RequestStatus
from app.requests.schemas import (
    AssignIn,
    DocumentOut,
    MessageOut,
    PersonRef,
    RequestDetail,
    RequestListItem,
    TransitionIn,
)
from app.requests.service import RequestService
from app.users.models import RolePermission, User

router = APIRouter(prefix="/api/v1/admin/requests", tags=["admin-requests"])

Reader = Requires(Perm.ADMIN_ACCESS, Perm.REQUESTS_READ)
Processor = Requires(Perm.ADMIN_ACCESS, Perm.REQUESTS_READ, Perm.REQUESTS_PROCESS)
Assigner = Requires(Perm.ADMIN_ACCESS, Perm.REQUESTS_READ, Perm.REQUESTS_ASSIGN)
# Transition-specific permissions (approve / reject) are checked by the state machine.
Transitioner = Requires(Perm.ADMIN_ACCESS, Perm.REQUESTS_READ)


@router.get("", response_model=Page[RequestListItem])
async def list_requests(
    db: DbSession,
    current: Reader,
    params: Annotated[PageParams, Depends()],
    status_filter: Annotated[RequestStatus | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    academic_year_id: uuid.UUID | None = None,
    branch_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    assigned: Annotated[str | None, Query(max_length=36, description="me | unassigned | <user id>")] = None,
):
    service = RequestService(db)
    rows, total = await service.list_for_staff(
        params,
        status=status_filter,
        q=q,
        academic_year_id=academic_year_id,
        branch_id=branch_id,
        category_id=category_id,
        assigned=assigned,
        current_user_id=current.id,
    )
    unread = await service.unread_counts([r.id for r in rows], AuthorSide.STAFF)
    return Page(
        items=[service.list_item(r, unread.get(r.id, 0), staff=True) for r in rows],
        total=total,
        limit=params.limit,
        offset=params.offset,
    )


@router.get("/assignees", response_model=list[PersonRef])
async def assignees(db: DbSession, _: Assigner):
    """Active staff members allowed to process requests."""
    roles = select(RolePermission.role).where(RolePermission.permission_code == Perm.REQUESTS_PROCESS.value)
    users = await db.scalars(
        select(User)
        .where(User.role.in_(roles), User.is_active.is_(True))
        .order_by(User.last_name, User.first_name)
    )
    return [PersonRef(id=u.id, first_name=u.first_name, last_name=u.last_name) for u in users.all()]


@router.get("/{request_id}", response_model=RequestDetail)
async def get_request(request_id: uuid.UUID, db: DbSession, current: Reader):
    service = RequestService(db)
    return await service.detail(await service.get(request_id), current, staff=True)


@router.post("/{request_id}/transitions", response_model=RequestDetail)
async def transition_request(
    request_id: uuid.UUID, data: TransitionIn, db: DbSession, current: Transitioner, ip: ClientIp
):
    await RequestActions(db).transition(request_id, data.to_status, data.comment, current, ip)
    service = RequestService(db)
    return await service.detail(await service.get(request_id), current, staff=True)


@router.post("/{request_id}/assign", response_model=RequestDetail)
async def assign_request(
    request_id: uuid.UUID, data: AssignIn, db: DbSession, current: Assigner, ip: ClientIp
):
    await RequestActions(db).assign(request_id, data.assignee_id, current, ip)
    service = RequestService(db)
    return await service.detail(await service.get(request_id), current, staff=True)


@router.post("/{request_id}/documents", response_model=list[DocumentOut], status_code=status.HTTP_201_CREATED)
async def upload_issued_documents(
    request_id: uuid.UUID,
    request: Request,
    db: DbSession,
    settings: SettingsDep,
    documents: DocumentsDep,
    current: Processor,
    ip: ClientIp,
):
    """multipart/form-data: final document(s) in the `files` field (PDF / PNG / JPEG).

    The files go through the same antivirus pipeline as student files (status SCANNING first).
    """
    form = await parse_multipart(request, settings)
    files = [f for name, f in form.files if name == "files"]
    if len(files) != len(form.files):
        raise AppError.of(422, "unexpected_file", "Files must be sent in the `files` field")
    docs = await RequestActions(db, documents).upload_issued(request_id, files, current, ip)
    return [DocumentOut.of(d, staff=True) for d in docs]


@router.get("/{request_id}/messages", response_model=list[MessageOut])
async def request_messages(request_id: uuid.UUID, db: DbSession, _: Reader):
    await RequestService(db).get(request_id)
    return await thread(db, request_id, AuthorSide.STAFF)


@router.post("/{request_id}/messages", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
async def post_message(
    request_id: uuid.UUID,
    request: Request,
    db: DbSession,
    settings: SettingsDep,
    documents: DocumentsDep,
    current: Processor,
    ip: ClientIp,
):
    """multipart/form-data: `body` + optional `files`."""
    form = await parse_multipart(request, settings)
    files = [f for name, f in form.files if name == "files"]
    if len(files) != len(form.files):
        raise AppError.of(422, "unexpected_file", "Files must be sent in the `files` field")
    await RequestActions(db, documents).post_message(
        request_id,
        form.fields.get("body"),
        files,
        current,
        side=AuthorSide.STAFF,
        student_id=None,
        respond=False,
        ip=ip,
    )
    return (await thread(db, request_id, AuthorSide.STAFF))[-1]


@router.post("/{request_id}/messages/read", status_code=status.HTTP_204_NO_CONTENT)
async def read_messages(request_id: uuid.UUID, db: DbSession, _: Reader) -> Response:
    await RequestService(db).get(request_id)
    await RequestActions(db).mark_messages_read(request_id, AuthorSide.STAFF)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{request_id}/documents/{document_id}/download")
async def download_document(
    request_id: uuid.UUID,
    document_id: uuid.UUID,
    db: DbSession,
    storage: StorageDep,
    current: Reader,
    ip: ClientIp,
) -> Response:
    doc = await find_document(db, request_id, document_id)
    return await download_response(db, storage, doc, actor_id=current.id, ip=ip)


@router.delete("/{request_id}/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_issued_document(
    request_id: uuid.UUID,
    document_id: uuid.UUID,
    db: DbSession,
    documents: DocumentsDep,
    current: Processor,
    ip: ClientIp,
) -> Response:
    """Removes a final document before delivery (PROCESSING / APPROVED), e.g. to replace it."""
    await RequestActions(db, documents).delete_issued(request_id, document_id, current, ip)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{request_id}/documents/{document_id}/rescan", response_model=DocumentOut)
async def rescan_document(
    request_id: uuid.UUID,
    document_id: uuid.UUID,
    db: DbSession,
    documents: DocumentsDep,
    current: Processor,
    ip: ClientIp,
):
    """Queues a new antivirus scan for a document whose scan ended in ERROR."""
    doc = await RequestActions(db, documents).rescan(request_id, document_id, current, ip)
    return DocumentOut.of(doc, staff=True)
