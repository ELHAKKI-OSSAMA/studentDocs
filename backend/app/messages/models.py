import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Index, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, UUIDPrimaryKey, str_enum
from app.users.models import User


class MessageKind(enum.StrEnum):
    MESSAGE = "MESSAGE"
    INFORMATION_REQUEST = "INFORMATION_REQUEST"  # sent with the NEEDS_INFORMATION transition
    INFORMATION_RESPONSE = "INFORMATION_RESPONSE"  # student answer that resumes the review


class AuthorSide(enum.StrEnum):
    STUDENT = "STUDENT"
    STAFF = "STAFF"


class RequestMessage(UUIDPrimaryKey, Base):
    __tablename__ = "request_messages"
    __table_args__ = (Index("ix_request_messages_request_seq", "request_id", "seq"),)

    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requests.id", ondelete="RESTRICT"), nullable=False
    )
    author_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    author_side: Mapped[AuthorSide] = mapped_column(
        str_enum(AuthorSide, "message_author_side"), nullable=False
    )
    kind: Mapped[MessageKind] = mapped_column(
        str_enum(MessageKind, "message_kind"), nullable=False, default=MessageKind.MESSAGE
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Thread order: a database sequence, immune to wall-clock adjustments (created_at can tie).
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # When the other side (student ↔ administration) read it.
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    author: Mapped[User] = relationship(lazy="joined")
