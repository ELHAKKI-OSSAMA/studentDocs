import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, SmallInteger, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPrimaryKey, str_enum
from app.emails.models import ReviewConfidence


class AiExtraction(UUIDPrimaryKey, Base):
    """One extraction attempt on an email case: a PROPOSAL for a human. Append-only (trigger).

    The email content itself is not copied here: `input_sha256` identifies exactly what was sent."""

    __tablename__ = "ai_extractions"

    email_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("email_cases.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    # Proof of where the data went: True only when the endpoint was verified to be on a private network.
    is_local_provider: Mapped[bool] = mapped_column(Boolean, nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    # Validated output (schema + catalogue + anchoring), NULL when the model failed.
    output: Mapped[dict | None] = mapped_column(JSONB)
    raw_output_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Deterministic completeness score (0-100) and level computed by the code, not by the model.
    review_score: Mapped[int | None] = mapped_column(SmallInteger)
    review_confidence: Mapped[ReviewConfidence | None] = mapped_column(
        str_enum(ReviewConfidence, "ai_review_confidence")
    )
    # Values dropped by validation (unknown catalogue code, value not found in the text, …).
    rule_violations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
