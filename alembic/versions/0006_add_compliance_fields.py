"""Add compliance fields to missions and execution_tasks.

Revision ID: 0006_add_compliance_fields
Revises: 0005_audit_events_rls
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0006_add_compliance_fields"
down_revision = "0005_audit_events_rls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "missions",
        sa.Column(
            "compliance_category",
            sa.String(length=64),
            nullable=False,
            server_default="operational",
        ),
    )
    op.add_column(
        "missions",
        sa.Column(
            "jurisdiction",
            sa.String(length=64),
            nullable=False,
            server_default="global",
        ),
    )

    op.add_column(
        "execution_tasks",
        sa.Column(
            "compliance_category",
            sa.String(length=64),
            nullable=False,
            server_default="operational",
        ),
    )
    op.add_column(
        "execution_tasks",
        sa.Column(
            "jurisdiction",
            sa.String(length=64),
            nullable=False,
            server_default="global",
        ),
    )
    op.add_column(
        "execution_tasks",
        sa.Column(
            "requires_human_review",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )

    op.create_index(
        "ix_missions_compliance_category",
        "missions",
        ["compliance_category"],
    )
    op.create_index(
        "ix_execution_tasks_compliance_category",
        "execution_tasks",
        ["compliance_category"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_execution_tasks_compliance_category",
        table_name="execution_tasks",
    )
    op.drop_index("ix_missions_compliance_category", table_name="missions")

    op.drop_column("execution_tasks", "requires_human_review")
    op.drop_column("execution_tasks", "jurisdiction")
    op.drop_column("execution_tasks", "compliance_category")
    op.drop_column("missions", "jurisdiction")
    op.drop_column("missions", "compliance_category")
