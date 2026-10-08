"""Student-facing request endpoints. Every lookup is scoped to the caller's own student record."""

import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import ValidationError
from sqlalchemy import select

from app.auth.dependencies import CurrentUser, Requires
from app.auth.permissions import Perm
from app.core.crud import Page, PageParams
from app.core.deps import ClientIp, DbSession, RateLimiterDep, SettingsDep, StorageDep
from app.core.errors import AppError
from app.documents.models import Document
from app.documents.service import download_response
from app.documents.upload import parse_multipart
from app.messages.models import AuthorSide
from app.messages.service import thread
from app.requests.actions import RequestActions
from app.requests.models import RequestStatus
from app.requests.schemas import (
    DocumentOut,
    IssuedDocumentOut,
    MessageOut,
    RequestCreate,
    RequestDetail,
    RequestListItem,
    RequestSummary,
)
from app.requests.service import RequestService, visible_documents
from app.students.models import Student
from app.students.service import StudentService

router = APIRouter(prefix="/api/v1/requests", tags=["requests"])

Creator = Requires(Perm.REQUEST_CREATE)
Owner = Requires(Perm.REQUEST_READ_OWN)


async def _student(db: DbSession, current: CurrentUser) -> Student:
    return await StudentService(db).for_user(current.id)


def _validation_error(exc: ValidationError) -> AppError:
    details = [{"loc": ["body", *e["loc"]], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    return AppError.of(422, "validation_error", "Invalid input", details)


@router.post("", response_model=RequestDetail, status_code=status.HTTP_201_CREATED)
async def create_request(
    request: Request,
    db: DbSession,
    settings: SettingsDep,
    storage: StorageDep,
    limiter: RateLimiterDep,
    current: Creator,
    ip: ClientIp,
):
    """multipart/form-data: `payload` (JSON, see RequestCreate) + `attachment:<document_type_id>` files."""
    await limiter.hit(
        "request-create",
        str(current.id),
        limit=settings.rate_limit_request_create_per_hour,
        window_seconds=3600,
    )
    form = await parse_multipart(request, settings)
    try:
        data = RequestCreate.model_validate(json.loads(form.fields.get("payload", "")))
    except json.JSONDecodeError as exc:
        raise AppError.of(422, "validation_error", "payload must be a JSON document") from exc
    except ValidationError as exc:
        raise _validation_error(exc) from exc
    service = RequestService(db)
    created = await service.create(await _student(db, current), data, form, storage, ip=ip)
    return await service.detail(created, current, staff=False)


@router.get("", response_model=Page[RequestListItem])
async def my_requests(
    db: DbSession,
    current: Owner,
    params: Annotated[PageParams, Depends()],
    status_filter: Annotated[RequestStatus | None, Query(alias="status")] = None,
):
    service = RequestService(db)
    student = await _student(db, current)
    rows, total = await service.list_for_student(student.id, status_filter, params)
    unread = await service.unread_counts([r.id for r in rows], AuthorSide.STUDENT)
    return Page(
        items=[service.list_item(r, unread.get(r.id, 0), staff=False) for r in rows],
        total=total,
        limit=params.limit,
        offset=params.offset,
    )


@router.get("/summary", response_model=RequestSummary)
async def my_summary(db: DbSession, current: Owner):
    return await RequestService(db).summary_for_student((await _student(db, current)).id)


@router.get("/documents", response_model=list[IssuedDocumentOut])
async def my_issued_documents(db: DbSession, current: Owner):
    rows = await RequestService(db).issued_documents_for_student((await _student(db, current)).id)
    return [
        IssuedDocumentOut(
            **DocumentOut.model_validate(doc).model_dump(), request_id=req.id, reference=req.reference
        )
        for doc, req in rows
    ]


@router.get("/{request_id}", response_model=RequestDetail)
async def my_request(request_id: uuid.UUID, db: DbSession, current: Owner):
    service = RequestService(db)
    req = await service.get_for_student(request_id, (await _student(db, current)).id)
    return await service.detail(req, current, staff=False)


@router.post("/{request_id}/cancel", response_model=RequestDetail)
async def cancel_my_request(request_id: uuid.UUID, db: DbSession, current: Owner, ip: ClientIp):
    student = await _student(db, current)
    await RequestActions(db).cancel_by_student(request_id, student.id, current, ip)
    service = RequestService(db)
    return await service.detail(await service.get(request_id), current, staff=False)


@router.get("/{request_id}/messages", response_model=list[MessageOut])
async def my_messages(request_id: uuid.UUID, db: DbSession, current: Owner):
    await RequestService(db).get_for_student(request_id, (await _student(db, current)).id)
    return await thread(db, request_id, AuthorSide.STUDENT)


async def _post(request_id, request, db, settings, storage, current, ip, *, respond: bool) -> MessageOut:
    student = await _student(db, current)
    form = await parse_multipart(request, settings)
    files = [f for name, f in form.files if name == "files"]
    if len(files) != len(form.files):
        raise AppError.of(422, "unexpected_file", "Files must be sent in the `files` field")
    await RequestActions(db, storage).post_message(
        request_id,
        form.fields.get("body"),
        files,
        current,
        side=AuthorSide.STUDENT,
        student_id=student.id,
        respond=respond,
        ip=ip,
    )
    messages = await thread(db, request_id, AuthorSide.STUDENT)
    return messages[-1]


@router.post("/{request_id}/messages", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
async def post_my_message(
    request_id: uuid.UUID,
    request: Request,
    db: DbSession,
    settings: SettingsDep,
    storage: StorageDep,
    current: Owner,
    ip: ClientIp,
):
    """multipart/form-data: `body` + optional `files`."""
    return await _post(request_id, request, db, settings, storage, current, ip, respond=False)


@router.post("/{request_id}/respond", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
async def respond_to_information_request(
    request_id: uuid.UUID,
    request: Request,
    db: DbSession,
    settings: SettingsDep,
    storage: StorageDep,
    current: Owner,
    ip: ClientIp,
):
    """Answers an information request (NEEDS_INFORMATION → IN_REVIEW).

    multipart/form-data: `body` + optional `files`.
    """
    return await _post(request_id, request, db, settings, storage, current, ip, respond=True)


@router.post("/{request_id}/messages/read", status_code=status.HTTP_204_NO_CONTENT)
async def read_my_messages(request_id: uuid.UUID, db: DbSession, current: Owner) -> Response:
    await RequestService(db).get_for_student(request_id, (await _student(db, current)).id)
    await RequestActions(db).mark_messages_read(request_id, AuthorSide.STUDENT)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{request_id}/documents/{document_id}/download")
async def download_my_document(
    request_id: uuid.UUID,
    document_id: uuid.UUID,
    db: DbSession,
    storage: StorageDep,
    current: Owner,
    ip: ClientIp,
) -> Response:
    service = RequestService(db)
    req = await service.get_for_student(request_id, (await _student(db, current)).id)
    doc = await db.scalar(select(Document).where(Document.id == document_id, Document.request_id == req.id))
    # Issued documents stay hidden until the request reaches an "available" status.
    if doc is not None and not visible_documents([doc], req, staff=False):
        doc = None
    return await download_response(db, storage, doc, actor_id=current.id, ip=ip)
