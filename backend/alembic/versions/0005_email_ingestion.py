"""Phase 4: inbound email (accounts, raw messages, cases, human reviews), AI extractions, email attachments.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-08 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_PERMISSIONS = {
    "emails.read": "List and read inbound email cases and their clean attachments",
    "emails.read_raw": "Download the raw .eml of an inbound email",
    "emails.process": "Assign, associate a student, correct, link, retry and re-extract email cases",
    "emails.convert": "Create a request from an inbound email case",
    "emails.dismiss": "Dismiss, ignore or reopen inbound email cases",
    "email_accounts.manage": "Manage watched mailboxes",
}
_STAFF = ["emails.read", "emails.read_raw", "emails.process", "emails.convert", "emails.dismiss"]
NEW_ROLE_PERMISSIONS = {
    "ADMIN": _STAFF,
    "SUPER_ADMIN": [*_STAFF, "email_accounts.manage"],
}
APPEND_ONLY_TABLES = ("email_messages", "email_case_reviews", "ai_extractions")

CASE_STATUSES = (
    "('NEW', 'AI_PROCESSING', 'NEEDS_REVIEW', 'CONVERTED', 'LINKED', 'DISMISSED', 'FAILED', 'IGNORED')"
)
CONFIDENCE = "('LOW', 'MEDIUM', 'HIGH')"
DECISIONS = (
    "('ASSOCIATE_STUDENT', 'CORRECT', 'CONVERT', 'LINK', 'DISMISS', 'IGNORE', 'REOPEN', 'RETRY', "
    "'REEXTRACT', 'ASSIGN')"
)
OLD_KINDS = "('ATTACHMENT', 'ISSUED', 'MESSAGE')"
NEW_KINDS = "('ATTACHMENT', 'ISSUED', 'MESSAGE', 'EMAIL_ATTACHMENT')"


def _enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=False, length=32)


def upgrade() -> None:
    op.create_table(
        "email_accounts",
        sa.Column("provider", _enum("IMAP", "MS_GRAPH", "GMAIL", name="email_provider"), nullable=False),
        sa.Column("address", postgresql.CITEXT(), nullable=False),
        sa.Column("folder", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("uid_validity", sa.BigInteger(), nullable=True),
        sa.Column("last_seen_uid", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=255), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "provider IN ('IMAP', 'MS_GRAPH', 'GMAIL')", name=op.f("ck_email_accounts_email_provider")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_accounts")),
        sa.UniqueConstraint("address", name=op.f("uq_email_accounts_address")),
    )

    op.create_table(
        "email_messages",
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("uid_validity", sa.BigInteger(), nullable=False),
        sa.Column("provider_uid", sa.BigInteger(), nullable=False),
        sa.Column("message_id_header", sa.String(length=998), nullable=True),
        sa.Column("in_reply_to", sa.Text(), nullable=True),
        sa.Column("references_header", sa.Text(), nullable=True),
        sa.Column("from_address", postgresql.CITEXT(), nullable=False),
        sa.Column("from_name", sa.String(length=255), nullable=True),
        sa.Column("to_addresses", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cc_addresses", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("subject", sa.String(length=998), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_storage_key", sa.String(length=255), nullable=False),
        sa.Column("raw_sha256", sa.String(length=64), nullable=False),
        sa.Column("raw_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("auth_results", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("provider_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.CheckConstraint("raw_size_bytes > 0", name=op.f("ck_email_messages_raw_size_positive")),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["email_accounts.id"],
            name=op.f("fk_email_messages_account_id_email_accounts"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_messages")),
        sa.UniqueConstraint("account_id", "uid_validity", "provider_uid", name="uq_email_messages_uid"),
        sa.UniqueConstraint("raw_storage_key", name=op.f("uq_email_messages_raw_storage_key")),
    )
    op.create_index(op.f("ix_email_messages_from_address"), "email_messages", ["from_address"], unique=False)
    op.create_index(op.f("ix_email_messages_raw_sha256"), "email_messages", ["raw_sha256"], unique=False)
    op.create_index("ix_email_messages_received_at", "email_messages", ["received_at"], unique=False)
    op.create_index(
        "uq_email_messages_message_id",
        "email_messages",
        ["account_id", "message_id_header"],
        unique=True,
        postgresql_where=sa.text("message_id_header IS NOT NULL"),
    )

    op.create_table(
        "email_cases",
        sa.Column("email_message_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            _enum(
                "NEW",
                "AI_PROCESSING",
                "NEEDS_REVIEW",
                "CONVERTED",
                "LINKED",
                "DISMISSED",
                "FAILED",
                "IGNORED",
                name="email_case_status",
            ),
            nullable=False,
        ),
        sa.Column("student_id", sa.UUID(), nullable=True),
        sa.Column(
            "identification_method",
            _enum("INSTITUTIONAL_EMAIL", "KNOWN_EMAIL", "ADMIN_MANUAL", name="email_identification_method"),
            nullable=True,
        ),
        sa.Column("candidate_students", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("detected_reference", sa.String(length=20), nullable=True),
        sa.Column("linked_request_id", sa.UUID(), nullable=True),
        sa.Column("flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("body_html_sanitized", sa.Text(), nullable=True),
        sa.Column(
            "review_confidence", _enum("LOW", "MEDIUM", "HIGH", name="email_review_confidence"), nullable=True
        ),
        sa.Column("assigned_to_id", sa.UUID(), nullable=True),
        sa.Column("reviewed_by_id", sa.UUID(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismiss_reason", sa.String(length=500), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(f"status IN {CASE_STATUSES}", name=op.f("ck_email_cases_email_case_status")),
        sa.CheckConstraint(
            "identification_method IN ('INSTITUTIONAL_EMAIL', 'KNOWN_EMAIL', 'ADMIN_MANUAL')",
            name=op.f("ck_email_cases_email_identification_method"),
        ),
        sa.CheckConstraint(
            f"review_confidence IN {CONFIDENCE}", name=op.f("ck_email_cases_email_review_confidence")
        ),
        sa.CheckConstraint(
            "status NOT IN ('CONVERTED', 'LINKED') OR linked_request_id IS NOT NULL",
            name=op.f("ck_email_cases_linked_request"),
        ),
        sa.CheckConstraint(
            "status <> 'CONVERTED' OR student_id IS NOT NULL", name=op.f("ck_email_cases_converted_student")
        ),
        sa.CheckConstraint(
            "status <> 'DISMISSED' OR dismiss_reason IS NOT NULL", name=op.f("ck_email_cases_dismiss_reason")
        ),
        sa.ForeignKeyConstraint(
            ["email_message_id"],
            ["email_messages.id"],
            name=op.f("fk_email_cases_email_message_id_email_messages"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["students.id"],
            name=op.f("fk_email_cases_student_id_students"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["linked_request_id"],
            ["requests.id"],
            name=op.f("fk_email_cases_linked_request_id_requests"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_to_id"],
            ["users.id"],
            name=op.f("fk_email_cases_assigned_to_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_id"],
            ["users.id"],
            name=op.f("fk_email_cases_reviewed_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_cases")),
        sa.UniqueConstraint("email_message_id", name=op.f("uq_email_cases_email_message_id")),
    )
    op.create_index("ix_email_cases_status_created_at", "email_cases", ["status", "created_at"], unique=False)
    op.create_index(op.f("ix_email_cases_student_id"), "email_cases", ["student_id"], unique=False)
    op.create_index(
        op.f("ix_email_cases_linked_request_id"), "email_cases", ["linked_request_id"], unique=False
    )
    op.create_index(op.f("ix_email_cases_assigned_to_id"), "email_cases", ["assigned_to_id"], unique=False)
    op.create_index(
        op.f("ix_email_cases_review_confidence"), "email_cases", ["review_confidence"], unique=False
    )

    op.create_table(
        "email_case_reviews",
        sa.Column("email_case_id", sa.UUID(), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=False),
        sa.Column(
            "decision",
            _enum(
                "ASSOCIATE_STUDENT",
                "CORRECT",
                "CONVERT",
                "LINK",
                "DISMISS",
                "IGNORE",
                "REOPEN",
                "RETRY",
                "REEXTRACT",
                "ASSIGN",
                name="email_review_decision",
            ),
            nullable=False,
        ),
        sa.Column("corrected_output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.CheckConstraint(
            f"decision IN {DECISIONS}", name=op.f("ck_email_case_reviews_email_review_decision")
        ),
        sa.ForeignKeyConstraint(
            ["email_case_id"],
            ["email_cases.id"],
            name=op.f("fk_email_case_reviews_email_case_id_email_cases"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name=op.f("fk_email_case_reviews_actor_id_users"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_case_reviews")),
    )
    op.create_index(
        op.f("ix_email_case_reviews_email_case_id"), "email_case_reviews", ["email_case_id"], unique=False
    )

    op.create_table(
        "ai_extractions",
        sa.Column("email_case_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column("is_local_provider", sa.Boolean(), nullable=False),
        sa.Column("input_sha256", sa.String(length=64), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_output_valid", sa.Boolean(), nullable=False),
        sa.Column("review_score", sa.SmallInteger(), nullable=True),
        sa.Column(
            "review_confidence", _enum("LOW", "MEDIUM", "HIGH", name="ai_review_confidence"), nullable=True
        ),
        sa.Column("rule_violations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.CheckConstraint(
            f"review_confidence IN {CONFIDENCE}", name=op.f("ck_ai_extractions_ai_review_confidence")
        ),
        sa.ForeignKeyConstraint(
            ["email_case_id"],
            ["email_cases.id"],
            name=op.f("fk_ai_extractions_email_case_id_email_cases"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_extractions")),
    )
    op.create_index(
        op.f("ix_ai_extractions_email_case_id"), "ai_extractions", ["email_case_id"], unique=False
    )

    # documents: email attachments exist before (and without) any request.
    op.add_column("documents", sa.Column("email_case_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_documents_email_case_id_email_cases"),
        "documents",
        "email_cases",
        ["email_case_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(op.f("ix_documents_email_case_id"), "documents", ["email_case_id"], unique=False)
    op.alter_column("documents", "request_id", existing_type=sa.UUID(), nullable=True)
    op.alter_column("documents", "uploaded_by_id", existing_type=sa.UUID(), nullable=True)
    op.drop_constraint(op.f("ck_documents_document_kind"), "documents", type_="check")
    op.create_check_constraint(op.f("ck_documents_document_kind"), "documents", f"kind IN {NEW_KINDS}")
    op.create_check_constraint(
        op.f("ck_documents_owner"), "documents", "num_nonnulls(request_id, email_case_id) >= 1"
    )
    op.create_check_constraint(
        op.f("ck_documents_uploader"), "documents", "uploaded_by_id IS NOT NULL OR kind = 'EMAIL_ATTACHMENT'"
    )

    for table in APPEND_ONLY_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION forbid_modification()"
        )

    permissions = sa.table("permissions", sa.column("code", sa.String), sa.column("description", sa.String))
    op.bulk_insert(permissions, [{"code": c, "description": d} for c, d in NEW_PERMISSIONS.items()])
    role_permissions = sa.table(
        "role_permissions", sa.column("role", sa.String), sa.column("permission_code", sa.String)
    )
    op.bulk_insert(
        role_permissions,
        [{"role": r, "permission_code": c} for r, codes in NEW_ROLE_PERMISSIONS.items() for c in codes],
    )


def downgrade() -> None:
    permissions = sa.table("permissions", sa.column("code", sa.String))
    # role_permissions rows go with them (ON DELETE CASCADE).
    op.execute(permissions.delete().where(permissions.c.code.in_(list(NEW_PERMISSIONS))))

    # Attachments already part of a request stay with it, as student attachments. The others cannot exist
    # without the email tables: their rows go (the objects stay in storage under tenants/<tenant>/emails/).
    op.execute(
        "UPDATE documents d SET kind = 'ATTACHMENT', uploaded_by_id = s.user_id "
        "FROM requests r JOIN students s ON s.id = r.student_id "
        "WHERE d.kind = 'EMAIL_ATTACHMENT' AND d.request_id = r.id"
    )
    op.execute("DELETE FROM documents WHERE kind = 'EMAIL_ATTACHMENT'")
    op.drop_constraint(op.f("ck_documents_uploader"), "documents", type_="check")
    op.drop_constraint(op.f("ck_documents_owner"), "documents", type_="check")
    op.drop_constraint(op.f("ck_documents_document_kind"), "documents", type_="check")
    op.create_check_constraint(op.f("ck_documents_document_kind"), "documents", f"kind IN {OLD_KINDS}")
    op.alter_column("documents", "uploaded_by_id", existing_type=sa.UUID(), nullable=False)
    op.alter_column("documents", "request_id", existing_type=sa.UUID(), nullable=False)
    op.drop_index(op.f("ix_documents_email_case_id"), table_name="documents")
    op.drop_constraint(op.f("fk_documents_email_case_id_email_cases"), "documents", type_="foreignkey")
    op.drop_column("documents", "email_case_id")

    op.drop_index(op.f("ix_ai_extractions_email_case_id"), table_name="ai_extractions")
    op.drop_table("ai_extractions")
    op.drop_index(op.f("ix_email_case_reviews_email_case_id"), table_name="email_case_reviews")
    op.drop_table("email_case_reviews")
    for index in (
        "ix_email_cases_review_confidence",
        "ix_email_cases_assigned_to_id",
        "ix_email_cases_linked_request_id",
        "ix_email_cases_student_id",
    ):
        op.drop_index(op.f(index), table_name="email_cases")
    op.drop_index("ix_email_cases_status_created_at", table_name="email_cases")
    op.drop_table("email_cases")
    op.drop_index(
        "uq_email_messages_message_id",
        table_name="email_messages",
        postgresql_where=sa.text("message_id_header IS NOT NULL"),
    )
    op.drop_index("ix_email_messages_received_at", table_name="email_messages")
    op.drop_index(op.f("ix_email_messages_raw_sha256"), table_name="email_messages")
    op.drop_index(op.f("ix_email_messages_from_address"), table_name="email_messages")
    op.drop_table("email_messages")
    op.drop_table("email_accounts")
