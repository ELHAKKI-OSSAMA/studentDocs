"""Lock the public schema against Supabase's auto-generated REST / GraphQL API.

Supabase exposes every table of `public` to its `anon` and `authenticated` roles (the anon key is public by
design). This application never uses that API: only the backend, connected as the database owner (which
bypasses RLS), reads and writes data. So: RLS on every table with no policy, and no privilege at all for
those two roles, now and for tables created later. A no-op on a plain PostgreSQL without these roles.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-02 18:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

API_ROLES = "anon, authenticated"


def upgrade() -> None:
    op.execute(
        f"""
        DO $$
        DECLARE t record;
        BEGIN
            FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
                EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t.tablename);
            END LOOP;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')
               AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {API_ROLES};
                REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {API_ROLES};
                REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM {API_ROLES};
                ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM {API_ROLES};
                ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM {API_ROLES};
                ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM {API_ROLES};
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # Privileges are not granted back: re-exposing the tables to the public API must be a deliberate choice.
    op.execute(
        """
        DO $$
        DECLARE t record;
        BEGIN
            FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
                EXECUTE format('ALTER TABLE public.%I DISABLE ROW LEVEL SECURITY', t.tablename);
            END LOOP;
        END $$;
        """
    )
