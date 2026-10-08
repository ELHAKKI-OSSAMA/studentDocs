"""Phase 3: antivirus pipeline (scan lifecycle, quarantine, soft delete, duplicate detection).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-08 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_STATUSES = "('NOT_SCANNED', 'SCANNING', 'CLEAN', 'INFECTED', 'ERROR')"
OLD_STATUSES = "('NOT_SCANNED', 'PENDING', 'CLEAN', 'INFECTED')"


def upgrade() -> None:
    op.add_column("documents", sa.Column("original_filename", sa.String(length=255), nullable=True))
    op.add_column("documents", sa.Column("scan_detail", sa.String(length=255), nullable=True))
    op.add_column("documents", sa.Column("scan_attempts", sa.Integer(), server_default="0", nullable=False))
    op.add_column("documents", sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("quarantined_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("deleted_by_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_documents_deleted_by_id_users"),
        "documents",
        "users",
        ["deleted_by_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.drop_constraint(op.f("ck_documents_scan_status"), "documents", type_="check")
    # Files stored before the antivirus existed were never scanned: they are queued now (the worker's
    # startup sweep picks every SCANNING document) instead of staying silently unscanned.
    op.execute(
        "UPDATE documents SET scan_status = 'SCANNING' WHERE scan_status IN ('NOT_SCANNED', 'PENDING')"
    )
    op.create_check_constraint(
        op.f("ck_documents_scan_status"), "documents", f"scan_status IN {NEW_STATUSES}"
    )

    op.create_index("ix_documents_sha256", "documents", ["sha256"], unique=False)
    op.create_index(
        "ix_documents_scanning",
        "documents",
        ["scan_status"],
        unique=False,
        postgresql_where=sa.text("scan_status = 'SCANNING'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_documents_scanning", table_name="documents", postgresql_where=sa.text("scan_status = 'SCANNING'")
    )
    op.drop_index("ix_documents_sha256", table_name="documents")
    op.drop_constraint(op.f("ck_documents_scan_status"), "documents", type_="check")
    op.execute(
        "UPDATE documents SET scan_status = CASE scan_status "
        "WHEN 'SCANNING' THEN 'PENDING' WHEN 'ERROR' THEN 'NOT_SCANNED' ELSE scan_status END"
    )
    op.create_check_constraint(
        op.f("ck_documents_scan_status"), "documents", f"scan_status IN {OLD_STATUSES}"
    )
    op.drop_constraint(op.f("fk_documents_deleted_by_id_users"), "documents", type_="foreignkey")
    for column in (
        "deleted_by_id",
        "deleted_at",
        "quarantined_at",
        "scanned_at",
        "scan_attempts",
        "scan_detail",
        "original_filename",
    ):
        op.drop_column("documents", column)
