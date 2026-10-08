"""Baseline: PostgreSQL extensions and shared trigger functions.

Revision ID: 0001
Revises:
Create Date: 2026-10-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")  # gen_random_uuid()
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")  # case-insensitive emails
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")  # fuzzy search / duplicate detection

    # Maintains updated_at columns.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    # Attached to append-only tables (audit_logs, status history) to forbid UPDATE/DELETE.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION forbid_modification() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'table % is append-only', TG_TABLE_NAME
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$ LANGUAGE plpgsql;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS forbid_modification()")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")
    # Extensions are intentionally kept: they may be shared with other schemas.
