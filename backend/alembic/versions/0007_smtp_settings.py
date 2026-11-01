"""Outgoing mail relay configured by a super-admin (single row, password encrypted).

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-01 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "smtp_settings",
        sa.Column("id", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("host", sa.String(length=253), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column(
            "security",
            sa.Enum("NONE", "SSL", "STARTTLS", name="smtp_security", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("password_encrypted", sa.Text(), nullable=True),
        sa.Column("mail_from", sa.String(length=320), nullable=False),
        sa.Column("updated_by_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_smtp_settings_singleton")),
        sa.CheckConstraint("port BETWEEN 1 AND 65535", name=op.f("ck_smtp_settings_port_range")),
        sa.ForeignKeyConstraint(
            ["updated_by_id"], ["users.id"], name=op.f("fk_smtp_settings_updated_by_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_smtp_settings")),
    )


def downgrade() -> None:
    op.drop_table("smtp_settings")
