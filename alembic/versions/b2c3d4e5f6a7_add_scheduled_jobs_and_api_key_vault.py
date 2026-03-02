"""add_scheduled_jobs_and_api_key_vault

Revision ID: b2c3d4e5f6a7
Revises: e1776d23c66e
Create Date: 2026-03-02 20:00:00.000000

Phase 2 (v6.1 — The Scheduled Agent):
  - scheduled_jobs: APScheduler-backed recurring/one-off mission triggers
  - external_api_keys: AES-256-GCM encrypted external API key vault

Built with Pride for Obex Blackvault
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b2c3d4e5f6a7"
down_revision = "e1776d23c66e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # scheduled_jobs
    # -------------------------------------------------------------------------
    op.create_table(
        "scheduled_jobs",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        # Ownership
        sa.Column(
            "tenant_id",
            sa.String(50),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            sa.String(50),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            sa.String(50),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=False,
        ),
        # Trigger configuration
        sa.Column("trigger_type", sa.String(20), nullable=False),
        sa.Column("cron_expression", sa.String(100), nullable=True),
        sa.Column("interval_seconds", sa.Integer, nullable=True),
        # Mission payload
        sa.Column("mission_payload", sa.JSON, nullable=False),
        # State
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("max_runs", sa.Integer, nullable=True),
        sa.Column("run_count", sa.Integer, nullable=False, server_default="0"),
        # Execution tracking
        sa.Column("last_run_at", sa.DateTime, nullable=True),
        sa.Column("next_run_at", sa.DateTime, nullable=True),
        sa.Column("last_run_status", sa.String(50), nullable=True),
        sa.Column("last_run_mission_id", sa.String(50), nullable=True),
        # Timestamps
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_scheduled_jobs_id", "scheduled_jobs", ["id"])
    op.create_index("ix_scheduled_jobs_tenant_id", "scheduled_jobs", ["tenant_id"])
    op.create_index("ix_scheduled_jobs_agent_id", "scheduled_jobs", ["agent_id"])
    op.create_index("ix_scheduled_jobs_is_active", "scheduled_jobs", ["is_active"])

    # -------------------------------------------------------------------------
    # external_api_keys
    # -------------------------------------------------------------------------
    op.create_table(
        "external_api_keys",
        sa.Column("id", sa.String(50), primary_key=True),
        # Ownership
        sa.Column(
            "tenant_id",
            sa.String(50),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            sa.String(50),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=False,
        ),
        # Key identity
        sa.Column("service", sa.String(100), nullable=False),
        sa.Column("key_name", sa.String(255), nullable=False),
        # Encrypted key material
        sa.Column("encrypted_value", sa.Text, nullable=False),
        sa.Column("nonce", sa.String(64), nullable=False),
        # Metadata
        sa.Column("metadata", sa.JSON, nullable=False, server_default="{}"),
        # State
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        # Timestamps
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("last_used_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_external_api_keys_id", "external_api_keys", ["id"])
    op.create_index("ix_external_api_keys_tenant_id", "external_api_keys", ["tenant_id"])
    op.create_index("ix_external_api_keys_service", "external_api_keys", ["service"])


def downgrade() -> None:
    op.drop_table("external_api_keys")
    op.drop_table("scheduled_jobs")
