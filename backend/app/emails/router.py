"""Staff endpoints for inbound email cases (/api/v1/admin/emails). No student endpoint exists."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response

from app.ai.factory import build_llm_provider
from app.auth.dependencies import Requires
from app.auth.permissions import Perm
from app.core.crud import Page, PageParams
from app.core.deps import ClientIp, DbSession, DocumentsDep, SettingsDep, StorageDep
from app.documents.service import download_response
from app.emails.cases import EmailCaseService, EmailTaskQueue
from app.emails.models import EmailCaseStatus, ReviewConfidence
from app.emails.schemas import (
    AssignCaseIn,
    AssociateStudentIn,
    CommentIn,
    ConvertIn,
    CorrectionIn,
    EmailCaseDetail,
    EmailCaseListItem,
    EmailStats,
    LinkIn,
    ReasonIn,
)
from app.requests.schemas import DocumentOut, RequestDetail
from app.requests.service import RequestService

router = APIRouter(prefix="/api/v1/admin/emails", tags=["admin-emails"])

Reader = Requires(Perm.ADMIN_ACCESS, Perm.EMAILS_READ)
RawReader = Requires(Perm.ADMIN_ACCESS, Perm.EMAILS_READ, Perm.EMAILS_READ_RAW)
Processor = Requires(Perm.ADMIN_ACCESS, Perm.EMAILS_READ, Perm.EMAILS_PROCESS)
Converter = Requires(Perm.ADMIN_ACCESS, Perm.EMAILS_READ, Perm.EMAILS_CONVERT, Perm.REQUESTS_PROCESS)
Dismisser = Requires(Perm.ADMIN_ACCESS, Perm.EMAILS_READ, Perm.EMAILS_DISMISS)


def get_email_tasks(request: Request) -> EmailTaskQueue | None:
    return getattr(request.app.state, "email_tasks", None)


EmailTasks = Annotated[EmailTaskQueue | None, Depends(get_email_tasks)]


def _service(db, settings, documents=None, tasks=None) -> EmailCaseService:
    return EmailCaseService(db, documents=documents, tasks=tasks, ai_enabled=settings.ai_provider != "none")


@router.get("", response_model=Page[EmailCaseListItem])
async def list_cases(
    db: DbSession,
    settings: SettingsDep,
    current: Reader,
    params: Annotated[PageParams, Depends()],
    status_filter: Annotated[EmailCaseStatus | None, Query(alias="status")] = None,
    confidence: ReviewConfidence | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    assigned: Annotated[str | None, Query(pattern="^(me|unassigned)$")] = None,
):
    service = _service(db, settings)
    rows, total = await service.search(
        params,
        status=status_filter,
        confidence=confidence,
        q=q,
        assigned=assigned,
        current_user_id=current.id,
    )
    return Page(items=await service.list_items(rows), total=total, limit=params.limit, offset=params.offset)


@router.get("/stats", response_model=EmailStats)
async def stats(db: DbSession, settings: SettingsDep, current: Reader):
    provider = build_llm_provider(settings)
    return await _service(db, settings).stats(
        ai_provider=settings.ai_provider, ai_is_local=provider.is_local if provider else None
    )


@router.get("/{case_id}", response_model=EmailCaseDetail)
async def get_case(case_id: uuid.UUID, db: DbSession, settings: SettingsDep, current: Reader):
    service = _service(db, settings)
    return await service.detail(await service.get(case_id), current)


async def _detail(service: EmailCaseService, case, current) -> EmailCaseDetail:
    return await service.detail(case, current)


@router.get("/{case_id}/raw")
async def download_raw(
    case_id: uuid.UUID,
    db: DbSession,
    settings: SettingsDep,
    storage: StorageDep,
    current: RawReader,
    ip: ClientIp,
) -> Response:
    """The original message (.eml) as received: download only (attachment, nosniff), audited."""
    return await _service(db, settings).raw_download(case_id, storage, current, ip)


@router.get("/{case_id}/documents/{document_id}/download")
async def download_attachment(
    case_id: uuid.UUID,
    document_id: uuid.UUID,
    db: DbSession,
    settings: SettingsDep,
    storage: StorageDep,
    current: Reader,
    ip: ClientIp,
) -> Response:
    """Phase 3 rules: only a CLEAN attachment is served (409 otherwise), every download is audited."""
    doc = await _service(db, settings).attachment(case_id, document_id)
    return await download_response(db, storage, doc, actor_id=current.id, ip=ip)


@router.post("/{case_id}/documents/{document_id}/rescan", response_model=DocumentOut)
async def rescan_attachment(
    case_id: uuid.UUID,
    document_id: uuid.UUID,
    db: DbSession,
    settings: SettingsDep,
    documents: DocumentsDep,
    current: Processor,
    ip: ClientIp,
):
    doc = await _service(db, settings, documents).rescan_attachment(case_id, document_id, current, ip)
    return DocumentOut.of(doc, staff=True)


@router.post("/{case_id}/assign", response_model=EmailCaseDetail)
async def assign(
    case_id: uuid.UUID,
    body: AssignCaseIn,
    db: DbSession,
    settings: SettingsDep,
    current: Processor,
    ip: ClientIp,
):
    service = _service(db, settings)
    return await _detail(service, await service.assign(case_id, body.assignee_id, current, ip), current)


@router.post("/{case_id}/student", response_model=EmailCaseDetail)
async def associate_student(
    case_id: uuid.UUID,
    body: AssociateStudentIn,
    db: DbSession,
    settings: SettingsDep,
    current: Processor,
    ip: ClientIp,
):
    service = _service(db, settings)
    case = await service.associate_student(case_id, body.student_id, body.comment, current, ip)
    return await _detail(service, case, current)


@router.put("/{case_id}/extraction", response_model=EmailCaseDetail)
async def correct_extraction(
    case_id: uuid.UUID,
    body: CorrectionIn,
    db: DbSession,
    settings: SettingsDep,
    current: Processor,
    ip: ClientIp,
):
    service = _service(db, settings)
    return await _detail(service, await service.correct(case_id, body, current, ip), current)


@router.post("/{case_id}/convert", response_model=RequestDetail, status_code=201)
async def convert(
    case_id: uuid.UUID,
    body: ConvertIn,
    db: DbSession,
    settings: SettingsDep,
    current: Converter,
    ip: ClientIp,
):
    request = await _service(db, settings).convert(case_id, body, current, ip)
    return await RequestService(db).detail(request, current, staff=True)


@router.post("/{case_id}/link", response_model=RequestDetail)
async def link(
    case_id: uuid.UUID, body: LinkIn, db: DbSession, settings: SettingsDep, current: Processor, ip: ClientIp
):
    request = await _service(db, settings).link(case_id, body, current, ip)
    return await RequestService(db).detail(request, current, staff=True)


@router.post("/{case_id}/dismiss", response_model=EmailCaseDetail)
async def dismiss(
    case_id: uuid.UUID, body: ReasonIn, db: DbSession, settings: SettingsDep, current: Dismisser, ip: ClientIp
):
    service = _service(db, settings)
    return await _detail(service, await service.dismiss(case_id, body.reason, current, ip), current)


@router.post("/{case_id}/ignore", response_model=EmailCaseDetail)
async def ignore(
    case_id: uuid.UUID, body: ReasonIn, db: DbSession, settings: SettingsDep, current: Dismisser, ip: ClientIp
):
    service = _service(db, settings)
    return await _detail(
        service, await service.dismiss(case_id, body.reason, current, ip, ignore=True), current
    )


@router.post("/{case_id}/reopen", response_model=EmailCaseDetail)
async def reopen(
    case_id: uuid.UUID,
    body: CommentIn,
    db: DbSession,
    settings: SettingsDep,
    tasks: EmailTasks,
    current: Dismisser,
    ip: ClientIp,
):
    service = _service(db, settings, tasks=tasks)
    return await _detail(service, await service.reopen(case_id, body.comment, current, ip), current)


@router.post("/{case_id}/retry", response_model=EmailCaseDetail)
async def retry(
    case_id: uuid.UUID,
    db: DbSession,
    settings: SettingsDep,
    tasks: EmailTasks,
    current: Processor,
    ip: ClientIp,
):
    service = _service(db, settings, tasks=tasks)
    return await _detail(service, await service.retry(case_id, current, ip), current)


@router.post("/{case_id}/reextract", response_model=EmailCaseDetail)
async def reextract(
    case_id: uuid.UUID,
    db: DbSession,
    settings: SettingsDep,
    tasks: EmailTasks,
    current: Processor,
    ip: ClientIp,
):
    service = _service(db, settings, tasks=tasks)
    return await _detail(service, await service.reextract(case_id, current, ip), current)
