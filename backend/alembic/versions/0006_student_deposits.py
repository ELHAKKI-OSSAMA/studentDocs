"""Originals deposited with the administration, and document types that withdraw them.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-30 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_PERMISSIONS = {"students.manage": "Record and return the originals a student deposited"}
NEW_ROLE_PERMISSIONS = {"ADMIN": ["students.manage"], "SUPER_ADMIN": ["students.manage"]}


def upgrade() -> None:
    op.add_column(
        "document_types",
        sa.Column("requires_deposit", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_table(
        "student_deposits",
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("document_type_id", sa.UUID(), nullable=False),
        sa.Column("deposited_on", sa.Date(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("recorded_by_id", sa.UUID(), nullable=True),
        sa.Column("returned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("returned_by_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_type_id"],
            ["document_types.id"],
            name=op.f("fk_student_deposits_document_type_id_document_types"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by_id"],
            ["users.id"],
            name=op.f("fk_student_deposits_recorded_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["returned_by_id"],
            ["users.id"],
            name=op.f("fk_student_deposits_returned_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["students.id"],
            name=op.f("fk_student_deposits_student_id_students"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_student_deposits")),
    )
    op.create_index(op.f("ix_student_deposits_student_id"), "student_deposits", ["student_id"], unique=False)
    op.create_index(
        "uq_student_deposits_open",
        "student_deposits",
        ["student_id", "document_type_id"],
        unique=True,
        postgresql_where=sa.text("returned_at IS NULL"),
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
    op.drop_index(
        "uq_student_deposits_open",
        table_name="student_deposits",
        postgresql_where=sa.text("returned_at IS NULL"),
    )
    op.drop_index(op.f("ix_student_deposits_student_id"), table_name="student_deposits")
    op.drop_table("student_deposits")
    op.drop_column("document_types", "requires_deposit")
