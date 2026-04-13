"""add_compliance_fields

Revision ID: 0005_add_compliance_fields
Revises: 0004_add_recovering_task_state
Create Date: 2026-04-03 10:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add compliance fields to missions table
    op.add_column(
        "missions", sa.Column("compliance_category", sa.String(length=64), server_default="operational", nullable=False)
    )
    op.add_column("missions", sa.Column("jurisdiction", sa.String(length=64), server_default="US-ALL", nullable=False))

    # Add compliance fields to execution_tasks table
    op.add_column(
        "execution_tasks",
        sa.Column("compliance_category", sa.String(length=64), server_default="operational", nullable=False),
    )
    op.add_column(
        "execution_tasks", sa.Column("jurisdiction", sa.String(length=64), server_default="US-ALL", nullable=False)
    )
    op.add_column(
        "execution_tasks", sa.Column("requires_human_review", sa.Boolean(), server_default="false", nullable=False)
    )
    op.add_column(
        "execution_tasks",
        sa.Column(
            "compliance_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("execution_tasks", "compliance_metadata")
    op.drop_column("execution_tasks", "requires_human_review")
    op.drop_column("execution_tasks", "jurisdiction")
    op.drop_column("execution_tasks", "compliance_category")
    op.drop_column("missions", "jurisdiction")
    op.drop_column("missions", "compliance_category")
