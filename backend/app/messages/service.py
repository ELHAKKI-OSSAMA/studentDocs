import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.models import Document
from app.messages.models import AuthorSide, RequestMessage
from app.requests.schemas import DocumentOut, MessageOut


async def thread(db: AsyncSession, request_id: uuid.UUID, viewer_side: AuthorSide) -> list[MessageOut]:
    messages = (
        await db.scalars(
            select(RequestMessage).where(RequestMessage.request_id == request_id).order_by(RequestMessage.seq)
        )
    ).all()
    attachments: dict[uuid.UUID, list[Document]] = defaultdict(list)
    if messages:
        docs = await db.scalars(
            select(Document)
            .where(Document.message_id.in_([m.id for m in messages]), Document.deleted_at.is_(None))
            .order_by(Document.created_at)
        )
        for doc in docs.all():
            attachments[doc.message_id].append(doc)
    out = []
    for m in messages:
        # Students see "Administration", never the individual staff member's identity.
        if m.author_side == AuthorSide.STAFF and viewer_side == AuthorSide.STUDENT:
            name = ""
        else:
            name = f"{m.author.first_name} {m.author.last_name}"
        out.append(
            MessageOut(
                id=m.id,
                author_side=m.author_side,
                author_name=name,
                kind=m.kind,
                body=m.body,
                created_at=m.created_at,
                read_at=m.read_at,
                attachments=[
                    DocumentOut.of(d, staff=viewer_side == AuthorSide.STAFF) for d in attachments[m.id]
                ],
            )
        )
    return out
