"""Add interpretation thread scoping to composition proposals.

Revision ID: 0036_composition_thread
Revises: 0035_composition_proposals
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0036_composition_thread"
down_revision = "0035_composition_proposals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mission_composition_proposals",
        sa.Column("interpretation_thread_id", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "mission_composition_proposals",
        sa.Column("proposal_kind", sa.String(length=40), nullable=False, server_default="interpretation"),
    )
    op.create_index(
        "ix_mission_composition_proposals_thread",
        "mission_composition_proposals",
        ["tenant_id", "actor_id", "interpretation_thread_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_mission_composition_proposals_thread", table_name="mission_composition_proposals")
    op.drop_column("mission_composition_proposals", "proposal_kind")
    op.drop_column("mission_composition_proposals", "interpretation_thread_id")
