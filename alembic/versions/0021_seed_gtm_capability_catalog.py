"""Seed global GTM capability catalog and adapters.

Revision ID: 0021_seed_gtm_capability_catalog
Revises: 0020_expand_lifecycle_checks
Create Date: 2026-05-27
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0021_seed_gtm_capability_catalog"
down_revision = "0020_expand_lifecycle_checks"
branch_labels = None
depends_on = None

CAPABILITY_TABLE = sa.table(
    "capabilities",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("tenant_id", sa.String(length=128)),
    sa.column("name", sa.String(length=160)),
    sa.column("version", sa.String(length=64)),
    sa.column("description", sa.Text()),
    sa.column("supported_task_types", postgresql.JSONB(astext_type=sa.Text())),
    sa.column("input_schema_hints", postgresql.JSONB(astext_type=sa.Text())),
    sa.column("output_schema_hints", postgresql.JSONB(astext_type=sa.Text())),
    sa.column("required_permissions", postgresql.JSONB(astext_type=sa.Text())),
    sa.column("required_tools", postgresql.JSONB(astext_type=sa.Text())),
    sa.column("risk_level", sa.String(length=32)),
    sa.column("approval_requirements", postgresql.JSONB(astext_type=sa.Text())),
    sa.column("evidence_expectations", postgresql.JSONB(astext_type=sa.Text())),
    sa.column("execution_constraints", postgresql.JSONB(astext_type=sa.Text())),
    sa.column("enabled", sa.Boolean()),
    sa.column("schema_version", sa.Integer()),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)

CAPABILITY_ADAPTER_TABLE = sa.table(
    "capability_adapters",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("tenant_id", sa.String(length=128)),
    sa.column("name", sa.String(length=160)),
    sa.column("version", sa.String(length=64)),
    sa.column("capability_id", postgresql.UUID(as_uuid=True)),
    sa.column("capability_name", sa.String(length=160)),
    sa.column("capability_version", sa.String(length=64)),
    sa.column("supported_task_types", postgresql.JSONB(astext_type=sa.Text())),
    sa.column("input_contract", postgresql.JSONB(astext_type=sa.Text())),
    sa.column("output_contract", postgresql.JSONB(astext_type=sa.Text())),
    sa.column("required_permissions", postgresql.JSONB(astext_type=sa.Text())),
    sa.column("required_tools", postgresql.JSONB(astext_type=sa.Text())),
    sa.column("execution_mode", sa.String(length=32)),
    sa.column("risk_level", sa.String(length=32)),
    sa.column("approval_requirements", postgresql.JSONB(astext_type=sa.Text())),
    sa.column("evidence_expectations", postgresql.JSONB(astext_type=sa.Text())),
    sa.column("timeout_retry_hints", postgresql.JSONB(astext_type=sa.Text())),
    sa.column("idempotency_expectations", postgresql.JSONB(astext_type=sa.Text())),
    sa.column("side_effect_classification", sa.String(length=64)),
    sa.column("enabled", sa.Boolean()),
    sa.column("schema_version", sa.Integer()),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)


def _create_global_seed_policy(conn: sa.Connection, table_name: str, policy_name: str) -> None:
    conn.execute(
        sa.text(
            f"""
            CREATE POLICY {policy_name} ON {table_name}
                AS PERMISSIVE
                FOR ALL
                TO PUBLIC
                USING (tenant_id IS NULL)
                WITH CHECK (tenant_id IS NULL)
            """
        )
    )


def _drop_seed_policy(conn: sa.Connection, table_name: str, policy_name: str) -> None:
    conn.execute(sa.text(f"DROP POLICY IF EXISTS {policy_name} ON {table_name}"))


def upgrade() -> None:
    conn = op.get_bind()
    _create_global_seed_policy(conn, "capabilities", "seed_global_gtm_capabilities_policy")
    _create_global_seed_policy(conn, "capability_adapters", "seed_global_gtm_capability_adapters_policy")
    try:
        conn.execute(
            sa.text(
                """
                INSERT INTO capabilities (
                    id, tenant_id, name, version, description,
                    supported_task_types, input_schema_hints, output_schema_hints,
                    required_permissions, required_tools, risk_level,
                    approval_requirements, evidence_expectations, execution_constraints,
                    enabled, schema_version, created_at, updated_at
                )
                VALUES (
                    gen_random_uuid(), NULL, 'gtm_outbound_email', '1.0.0',
                    'Global GTM outbound email planning capability.',
                    '["outbound_campaign"]'::jsonb,
                    '{"required": ["campaign_brief"]}'::jsonb,
                    '{"produces": ["outbound_plan"]}'::jsonb,
                    '[]'::jsonb,
                    '["email"]'::jsonb,
                    'high',
                    '{"human_approval": true}'::jsonb,
                    '["approval_decision", "send_outcome"]'::jsonb,
                    '{"policy_gated": true, "feature_flag": "gtm_enabled"}'::jsonb,
                    true, 1, now(), now()
                )
                ON CONFLICT (name, version)
                WHERE tenant_id IS NULL
                DO NOTHING
                """
            )
        )

        conn.execute(
            sa.text(
                """
                INSERT INTO capability_adapters (
                    id, tenant_id, name, version, capability_id,
                    capability_name, capability_version, supported_task_types,
                    input_contract, output_contract, required_permissions, required_tools,
                    execution_mode, risk_level, approval_requirements, evidence_expectations,
                    timeout_retry_hints, idempotency_expectations, side_effect_classification,
                    enabled, schema_version, created_at, updated_at
                )
                SELECT
                    gen_random_uuid(), NULL, 'gtm_outbound_email_adapter', '1.0.0', c.id,
                    c.name, c.version, '["outbound_campaign"]'::jsonb,
                    '{"required": ["campaign_brief"]}'::jsonb,
                    '{"produces": ["delivery_payload"]}'::jsonb,
                    '[]'::jsonb, '["email"]'::jsonb,
                    'declarative', 'high',
                    '{"human_approval": true}'::jsonb,
                    '["approval_decision", "delivery_outcome"]'::jsonb,
                    '{"timeout_seconds": 120, "max_retries": 1}'::jsonb,
                    '{"idempotency_key_required": true}'::jsonb,
                    'external_side_effect',
                    true, 1, now(), now()
                FROM capabilities c
                WHERE c.tenant_id IS NULL
                  AND c.name = 'gtm_outbound_email'
                  AND c.version = '1.0.0'
                ON CONFLICT (name, version)
                WHERE tenant_id IS NULL
                DO NOTHING
                """
            )
        )
    finally:
        _drop_seed_policy(conn, "capability_adapters", "seed_global_gtm_capability_adapters_policy")
        _drop_seed_policy(conn, "capabilities", "seed_global_gtm_capabilities_policy")


def downgrade() -> None:
    conn = op.get_bind()
    _create_global_seed_policy(conn, "capabilities", "seed_global_gtm_capabilities_policy")
    _create_global_seed_policy(conn, "capability_adapters", "seed_global_gtm_capability_adapters_policy")
    try:
        conn.execute(
            sa.text(
                """
                DELETE FROM capability_adapters
                WHERE tenant_id IS NULL
                  AND name = 'gtm_outbound_email_adapter'
                  AND version = '1.0.0'
                """
            )
        )
        conn.execute(
            sa.text(
                """
                DELETE FROM capabilities
                WHERE tenant_id IS NULL
                  AND name = 'gtm_outbound_email'
                  AND version = '1.0.0'
                """
            )
        )
    finally:
        _drop_seed_policy(conn, "capability_adapters", "seed_global_gtm_capability_adapters_policy")
        _drop_seed_policy(conn, "capabilities", "seed_global_gtm_capabilities_policy")
