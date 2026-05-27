"""Seed declarative GTM capability and adapter records.

Revision ID: 0021_seed_gtm_declarative
Revises: 0020_expand_lifecycle_checks
Create Date: 2026-05-27 00:00:00.000000
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0021_seed_gtm_declarative"
down_revision = "0020_expand_lifecycle_checks"
branch_labels = None
depends_on = None


def _now() -> datetime:
    return datetime.now(tz=UTC)


def upgrade() -> None:
    now = _now()
    capabilities_table = sa.table(
        "capabilities",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("tenant_id", sa.String),
        sa.column("name", sa.String),
        sa.column("version", sa.String),
        sa.column("description", sa.Text),
        sa.column("supported_task_types", postgresql.JSONB),
        sa.column("input_schema_hints", postgresql.JSONB),
        sa.column("output_schema_hints", postgresql.JSONB),
        sa.column("required_permissions", postgresql.JSONB),
        sa.column("required_tools", postgresql.JSONB),
        sa.column("risk_level", sa.String),
        sa.column("approval_requirements", postgresql.JSONB),
        sa.column("evidence_expectations", postgresql.JSONB),
        sa.column("execution_constraints", postgresql.JSONB),
        sa.column("enabled", sa.Boolean),
        sa.column("schema_version", sa.Integer),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )

    op.bulk_insert(
        capabilities_table,
        [
            {
                "id": UUID("11111111-1111-4111-8111-111111111111"),
                "tenant_id": None,
                "name": "gtm.lead.discovery.query_builder",
                "version": "1.0.0",
                "description": "Generates ICP-aligned lead discovery query sets.",
                "supported_task_types": ["analysis"],
                "input_schema_hints": {"mission_family": "lead_discovery", "channel": "web"},
                "output_schema_hints": {"artifact": "query_set"},
                "required_permissions": [],
                "required_tools": [],
                "risk_level": "low",
                "approval_requirements": {"mode": "none", "requires_human_gate": False},
                "evidence_expectations": ["query_provenance", "selection_rationale"],
                "execution_constraints": {"authority_class": "declarative", "runtime_binding_allowed": False},
                "enabled": True,
                "schema_version": 1,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": UUID("22222222-2222-4222-8222-222222222222"),
                "tenant_id": None,
                "name": "gtm.outbound.message_draft",
                "version": "1.0.0",
                "description": "Generates outbound message drafts without send authority.",
                "supported_task_types": ["analysis", "content_generation"],
                "input_schema_hints": {"mission_family": "outbound_sequencing", "channel": "email_linkedin"},
                "output_schema_hints": {"artifact": "draft_message"},
                "required_permissions": [],
                "required_tools": [],
                "risk_level": "medium",
                "approval_requirements": {"mode": "required", "requires_human_gate": True},
                "evidence_expectations": ["draft_artifact", "policy_reference"],
                "execution_constraints": {"authority_class": "declarative", "runtime_binding_allowed": False},
                "enabled": True,
                "schema_version": 1,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": UUID("33333333-3333-4333-8333-333333333333"),
                "tenant_id": None,
                "name": "gtm.content.publish_dispatch",
                "version": "1.0.0",
                "description": "Represents high-risk publish dispatch contracts with runtime binding disabled.",
                "supported_task_types": ["notification"],
                "input_schema_hints": {"mission_family": "content_pipeline", "channel": "social_blog"},
                "output_schema_hints": {"artifact": "publish_dispatch_envelope"},
                "required_permissions": ["content.publish"],
                "required_tools": ["publisher_adapter"],
                "risk_level": "high",
                "approval_requirements": {"mode": "multi_party_required", "requires_human_gate": True},
                "evidence_expectations": ["approval_record", "policy_reference", "dispatch_intent"],
                "execution_constraints": {"authority_class": "declarative", "runtime_binding_allowed": False},
                "enabled": False,
                "schema_version": 1,
                "created_at": now,
                "updated_at": now,
            },
        ],
    )

    adapters_table = sa.table(
        "capability_adapters",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("tenant_id", sa.String),
        sa.column("name", sa.String),
        sa.column("version", sa.String),
        sa.column("capability_id", postgresql.UUID(as_uuid=True)),
        sa.column("capability_name", sa.String),
        sa.column("capability_version", sa.String),
        sa.column("supported_task_types", postgresql.JSONB),
        sa.column("input_contract", postgresql.JSONB),
        sa.column("output_contract", postgresql.JSONB),
        sa.column("required_permissions", postgresql.JSONB),
        sa.column("required_tools", postgresql.JSONB),
        sa.column("execution_mode", sa.String),
        sa.column("risk_level", sa.String),
        sa.column("approval_requirements", postgresql.JSONB),
        sa.column("evidence_expectations", postgresql.JSONB),
        sa.column("timeout_retry_hints", postgresql.JSONB),
        sa.column("idempotency_expectations", postgresql.JSONB),
        sa.column("side_effect_classification", sa.String),
        sa.column("enabled", sa.Boolean),
        sa.column("schema_version", sa.Integer),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )

    op.bulk_insert(
        adapters_table,
        [
            {
                "id": UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
                "tenant_id": None,
                "name": "gtm.adapter.lead.query_builder",
                "version": "1.0.0",
                "capability_id": UUID("11111111-1111-4111-8111-111111111111"),
                "capability_name": "gtm.lead.discovery.query_builder",
                "capability_version": "1.0.0",
                "supported_task_types": ["analysis"],
                "input_contract": {"schema": "lead_query_builder.v1"},
                "output_contract": {"schema": "lead_query_set.v1"},
                "required_permissions": [],
                "required_tools": [],
                "execution_mode": "declarative",
                "risk_level": "low",
                "approval_requirements": {"mode": "none"},
                "evidence_expectations": ["query_provenance"],
                "timeout_retry_hints": {"timeout_seconds": 30, "max_retries": 0},
                "idempotency_expectations": {"required": False},
                "side_effect_classification": "none",
                "enabled": True,
                "schema_version": 1,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
                "tenant_id": None,
                "name": "gtm.adapter.outbound.message_draft",
                "version": "1.0.0",
                "capability_id": UUID("22222222-2222-4222-8222-222222222222"),
                "capability_name": "gtm.outbound.message_draft",
                "capability_version": "1.0.0",
                "supported_task_types": ["analysis", "content_generation"],
                "input_contract": {"schema": "outbound_draft_input.v1"},
                "output_contract": {"schema": "outbound_draft_output.v1"},
                "required_permissions": [],
                "required_tools": [],
                "execution_mode": "declarative",
                "risk_level": "medium",
                "approval_requirements": {"mode": "required"},
                "evidence_expectations": ["draft_artifact", "policy_reference"],
                "timeout_retry_hints": {"timeout_seconds": 45, "max_retries": 0},
                "idempotency_expectations": {"required": True, "key_scope": "tenant_mission_task"},
                "side_effect_classification": "none",
                "enabled": True,
                "schema_version": 1,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
                "tenant_id": None,
                "name": "gtm.adapter.content.publish_dispatch",
                "version": "1.0.0",
                "capability_id": UUID("33333333-3333-4333-8333-333333333333"),
                "capability_name": "gtm.content.publish_dispatch",
                "capability_version": "1.0.0",
                "supported_task_types": ["notification"],
                "input_contract": {"schema": "content_publish_dispatch_input.v1"},
                "output_contract": {"schema": "content_publish_dispatch_output.v1"},
                "required_permissions": ["content.publish"],
                "required_tools": ["publisher_adapter"],
                "execution_mode": "declarative",
                "risk_level": "high",
                "approval_requirements": {"mode": "multi_party_required"},
                "evidence_expectations": ["approval_record", "dispatch_intent", "policy_reference"],
                "timeout_retry_hints": {"timeout_seconds": 60, "max_retries": 0},
                "idempotency_expectations": {"required": True, "key_scope": "tenant_mission_task"},
                "side_effect_classification": "external_side_effect",
                "enabled": False,
                "schema_version": 1,
                "created_at": now,
                "updated_at": now,
            },
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM capability_adapters WHERE id IN (:a, :b, :c)").bindparams(
            a=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
            b=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
            c=UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
        )
    )
    op.execute(
        sa.text("DELETE FROM capabilities WHERE id IN (:x, :y, :z)").bindparams(
            x=UUID("11111111-1111-4111-8111-111111111111"),
            y=UUID("22222222-2222-4222-8222-222222222222"),
            z=UUID("33333333-3333-4333-8333-333333333333"),
        )
    )
