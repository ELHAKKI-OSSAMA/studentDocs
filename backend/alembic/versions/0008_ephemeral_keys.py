"""Short-lived keys in PostgreSQL (rate limits, revoked access tokens) for deployments without Redis.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-02 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ephemeral_keys",
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("value", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_ephemeral_keys")),
    )
    op.create_index(op.f("ix_ephemeral_keys_expires_at"), "ephemeral_keys", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_ephemeral_keys_expires_at"), table_name="ephemeral_keys")
    op.drop_table("ephemeral_keys")
