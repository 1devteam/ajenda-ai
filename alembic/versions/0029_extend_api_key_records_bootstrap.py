"""Extend api_key_records for bootstrap vs operational keys.

Revision ID: 0029_api_key_bootstrap
Revises: 0028_add_tenant_members
Create Date: 2026-06-21

Adds purpose, expires_at, and roles_json. Existing rows backfill to
purpose=operational and roles_json=['machine_executor'] for backward compatibility.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0029_api_key_bootstrap"
down_revision = "0028_add_tenant_members"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "api_key_records",
        sa.Column(
            "purpose",
            sa.String(32),
            nullable=False,
            server_default="operational",
            comment="operational | bootstrap",
        ),
    )
    op.add_column(
        "api_key_records",
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Required when purpose=bootstrap",
        ),
    )
    op.add_column(
        "api_key_records",
        sa.Column(
            "roles_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[\"machine_executor\"]'::jsonb"),
            comment="RBAC role names for machine principal resolution",
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE api_key_records
            SET roles_json = '["machine_executor"]'::jsonb
            WHERE roles_json IS NULL OR roles_json = '[]'::jsonb
            """
        )
    )
    op.create_check_constraint(
        "ck_api_key_records_bootstrap_expires",
        "api_key_records",
        "purpose != 'bootstrap' OR expires_at IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_api_key_records_bootstrap_expires", "api_key_records", type_="check")
    op.drop_column("api_key_records", "roles_json")
    op.drop_column("api_key_records", "expires_at")
    op.drop_column("api_key_records", "purpose")