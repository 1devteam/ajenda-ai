"""Add durable mission composition proposal / interpretation history.

Revision ID: 0035_mission_composition_proposals
Revises: 0034_email_send_idempotency
Create Date: 2026-07-27

Declarative store only — does not grant runtime execution authority.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0035_mission_composition_proposals"
down_revision = "0034_email_send_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mission_composition_proposals",
        sa.Column("id", sa.String(length=160), nullable=False),
        sa.Column("tenant_id", sa.String(length=160), nullable=False),
        sa.Column("proposal_id", sa.String(length=80), nullable=False),
        sa.Column("actor_id", sa.String(length=240), nullable=True),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("normalized_instruction", sa.Text(), nullable=True),
        sa.Column("interpreter_version", sa.String(length=40), nullable=False),
        sa.Column("components_active", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("record_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("ready_to_start", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("failure_reason", sa.String(length=500), nullable=True),
        sa.Column("restatement_requirement", sa.Text(), nullable=True),
        sa.Column("recognized_clauses", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("unmatched_clauses", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("unresolved_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("canonical_outcomes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("send_policy_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("coverage_score", sa.Float(), nullable=True),
        sa.Column("repeated_failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("superseded_proposal_id", sa.String(length=80), nullable=True),
        sa.Column("superseding_proposal_id", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="active"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "proposal_id", name="uq_mission_composition_proposals_tenant_proposal"),
    )
    op.create_index(
        "ix_mission_composition_proposals_tenant_id",
        "mission_composition_proposals",
        ["tenant_id"],
    )
    op.create_index(
        "ix_mission_composition_proposals_proposal_id",
        "mission_composition_proposals",
        ["proposal_id"],
    )
    op.create_index(
        "ix_mission_composition_proposals_tenant_status",
        "mission_composition_proposals",
        ["tenant_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_mission_composition_proposals_tenant_status", table_name="mission_composition_proposals")
    op.drop_index("ix_mission_composition_proposals_proposal_id", table_name="mission_composition_proposals")
    op.drop_index("ix_mission_composition_proposals_tenant_id", table_name="mission_composition_proposals")
    op.drop_table("mission_composition_proposals")
