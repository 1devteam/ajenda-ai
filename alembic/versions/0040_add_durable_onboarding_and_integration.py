"""Add durable onboarding state and explicit credential integrations."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0040_onboarding_connectors"
down_revision = "0039_add_password_login"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_onboarding_states",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("setup_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by_member_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["completed_by_member_id"], ["tenant_members.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("tenant_id"),
    )
    op.create_table(
        "member_onboarding_preferences",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("member_id", sa.UUID(), nullable=False),
        sa.Column("suppress_setup_prompt", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("suppressed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["member_id"], ["tenant_members.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tenant_id", "member_id"),
    )
    op.add_column(
        "provider_runtime_credentials",
        sa.Column("integration", sa.String(length=80), nullable=False, server_default="generic"),
    )
    op.execute(
        sa.text(
            "UPDATE provider_runtime_credentials SET integration = CASE "
            "WHEN credential_id = 'gmail-email' THEN 'gmail' "
            "WHEN credential_id = 'google-calendar-read' THEN 'google_calendar' "
            "WHEN credential_id = 'google-contacts-read' THEN 'google_contacts' "
            "WHEN credential_id = 'hubspot-crm' THEN 'hubspot' "
            "WHEN credential_id = 'ajenda-email' THEN 'smtp' "
            "WHEN credential_id = 'github-read' THEN 'github' "
            "WHEN credential_id = 'linkedin-read' THEN 'linkedin' "
            "WHEN credential_id = 'salesforce-read' THEN 'salesforce' "
            "ELSE 'generic' END"
        )
    )


def downgrade() -> None:
    op.drop_column("provider_runtime_credentials", "integration")
    op.drop_table("member_onboarding_preferences")
    op.drop_table("tenant_onboarding_states")
