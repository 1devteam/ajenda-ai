"""add_workforce_tables

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-02

Phase 4 — The Coordinating Agent (v6.3)

Adds two new tables:
  - workforces:        Persistent workforce configurations (name, roles, pipeline_type)
  - workforce_members: Agent-to-role assignments within a workforce

Both tables are tenant-scoped and include full audit timestamps.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # workforces
    # ------------------------------------------------------------------
    op.create_table(
        "workforces",
        sa.Column("id", sa.String(50), primary_key=True, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "tenant_id",
            sa.String(50),
            sa.ForeignKey("tenants.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "created_by",
            sa.String(50),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("roles", sa.JSON, nullable=False),
        sa.Column("pipeline_type", sa.String(20), nullable=False, server_default="sequential"),
        sa.Column("default_budget", sa.Float, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("total_runs", sa.Integer, nullable=False, server_default="0"),
        sa.Column("successful_runs", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failed_runs", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column("last_run_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_workforces_tenant_id", "workforces", ["tenant_id"])
    op.create_index("ix_workforces_is_active", "workforces", ["is_active"])

    # ------------------------------------------------------------------
    # workforce_members
    # ------------------------------------------------------------------
    op.create_table(
        "workforce_members",
        sa.Column("id", sa.String(50), primary_key=True, index=True),
        sa.Column(
            "workforce_id",
            sa.String(50),
            sa.ForeignKey("workforces.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "agent_id",
            sa.String(50),
            sa.ForeignKey("agents.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("role", sa.String(50), nullable=False, index=True),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_workforce_members_workforce_id", "workforce_members", ["workforce_id"]
    )
    op.create_index(
        "ix_workforce_members_agent_id", "workforce_members", ["agent_id"]
    )
    op.create_index(
        "ix_workforce_members_role", "workforce_members", ["role"]
    )


def downgrade() -> None:
    op.drop_table("workforce_members")
    op.drop_table("workforces")
