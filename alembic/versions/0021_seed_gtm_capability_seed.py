"""Seed global GTM declarative capability and adapter contracts.

Revision ID: 0021_seed_gtm_capability_seed
Revises: 0020_expand_lifecycle_checks
Create Date: 2026-05-27 00:00:00.000000
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0021_seed_gtm_capability_seed"
down_revision = "0020_expand_lifecycle_checks"
branch_labels = None
depends_on = None


def _capability_rows(now: datetime) -> list[dict[str, object]]:
    return [
        {
            "id": uuid.UUID("c3a4c98f-878f-48d2-957e-56baae5f7cf3"),
            "tenant_id": None,
            "name": "gtm.lead_discovery",
            "version": "1.0.0",
            "description": "Declarative GTM contract for lead discovery and qualification planning.",
            "supported_task_types": ["gtm.lead.discovery"],
            "input_schema_hints": {"type": "object", "required": ["persona", "segments"]},
            "output_schema_hints": {"type": "object", "required": ["lead_candidates"]},
            "required_permissions": ["gtm:read"],
            "required_tools": ["crm", "enrichment"],
            "risk_level": "medium",
            "approval_requirements": {"human_review_required": True},
            "evidence_expectations": ["lead_source_trace", "qualification_rationale"],
            "execution_constraints": {"runtime_binding": "forbidden", "outbound_send": "forbidden"},
            "enabled": True,
            "schema_version": 1,
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": uuid.UUID("9c12600f-9d90-4977-aef2-ab76cbf0e18e"),
            "tenant_id": None,
            "name": "gtm.outreach_sequence",
            "version": "1.0.0",
            "description": "Declarative GTM contract for outbound sequence planning metadata.",
            "supported_task_types": ["gtm.outreach.sequence"],
            "input_schema_hints": {"type": "object", "required": ["audience", "message_objective"]},
            "output_schema_hints": {"type": "object", "required": ["sequence_steps"]},
            "required_permissions": ["gtm:read"],
            "required_tools": ["crm", "email"],
            "risk_level": "high",
            "approval_requirements": {"human_review_required": True, "publish_gate": "required"},
            "evidence_expectations": ["policy_gate_result", "approval_receipt"],
            "execution_constraints": {"runtime_binding": "forbidden", "channel_send": "forbidden"},
            "enabled": True,
            "schema_version": 1,
            "created_at": now,
            "updated_at": now,
        },
    ]


def _adapter_rows(now: datetime) -> list[dict[str, object]]:
    return [
        {
            "id": uuid.UUID("4c6388a9-997f-4fba-8c3d-e9b8ea9f9b8b"),
            "tenant_id": None,
            "name": "gtm.lead_discovery.declarative",
            "version": "1.0.0",
            "capability_id": uuid.UUID("c3a4c98f-878f-48d2-957e-56baae5f7cf3"),
            "capability_name": "gtm.lead_discovery",
            "capability_version": "1.0.0",
            "supported_task_types": ["gtm.lead.discovery"],
            "input_contract": {"schema_ref": "gtm.lead.discovery.input.v1"},
            "output_contract": {"schema_ref": "gtm.lead.discovery.output.v1"},
            "required_permissions": ["gtm:read"],
            "required_tools": ["crm", "enrichment"],
            "execution_mode": "declarative",
            "risk_level": "medium",
            "approval_requirements": {"human_review_required": True},
            "evidence_expectations": ["lead_source_trace", "qualification_rationale"],
            "timeout_retry_hints": {"class": "declarative_only"},
            "idempotency_expectations": {"safe": True, "reason": "no runtime side effects"},
            "side_effect_classification": "none",
            "enabled": True,
            "schema_version": 1,
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": uuid.UUID("b512ee42-8cb9-4124-9d95-4fef59ceac5d"),
            "tenant_id": None,
            "name": "gtm.outreach_sequence.declarative",
            "version": "1.0.0",
            "capability_id": uuid.UUID("9c12600f-9d90-4977-aef2-ab76cbf0e18e"),
            "capability_name": "gtm.outreach_sequence",
            "capability_version": "1.0.0",
            "supported_task_types": ["gtm.outreach.sequence"],
            "input_contract": {"schema_ref": "gtm.outreach.sequence.input.v1"},
            "output_contract": {"schema_ref": "gtm.outreach.sequence.output.v1"},
            "required_permissions": ["gtm:read"],
            "required_tools": ["crm", "email"],
            "execution_mode": "declarative",
            "risk_level": "high",
            "approval_requirements": {"human_review_required": True, "publish_gate": "required"},
            "evidence_expectations": ["policy_gate_result", "approval_receipt"],
            "timeout_retry_hints": {"class": "declarative_only"},
            "idempotency_expectations": {"safe": True, "reason": "no runtime side effects"},
            "side_effect_classification": "none",
            "enabled": True,
            "schema_version": 1,
            "created_at": now,
            "updated_at": now,
        },
    ]


def upgrade() -> None:
    now = datetime.now(tz=UTC)

    capabilities_table = sa.table(
        "capabilities",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("tenant_id", sa.String(128)),
        sa.column("name", sa.String(160)),
        sa.column("version", sa.String(64)),
        sa.column("description", sa.Text()),
        sa.column("supported_task_types", postgresql.JSONB),
        sa.column("input_schema_hints", postgresql.JSONB),
        sa.column("output_schema_hints", postgresql.JSONB),
        sa.column("required_permissions", postgresql.JSONB),
        sa.column("required_tools", postgresql.JSONB),
        sa.column("risk_level", sa.String(32)),
        sa.column("approval_requirements", postgresql.JSONB),
        sa.column("evidence_expectations", postgresql.JSONB),
        sa.column("execution_constraints", postgresql.JSONB),
        sa.column("enabled", sa.Boolean()),
        sa.column("schema_version", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )

    adapters_table = sa.table(
        "capability_adapters",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("tenant_id", sa.String(128)),
        sa.column("name", sa.String(160)),
        sa.column("version", sa.String(64)),
        sa.column("capability_id", postgresql.UUID(as_uuid=True)),
        sa.column("capability_name", sa.String(160)),
        sa.column("capability_version", sa.String(64)),
        sa.column("supported_task_types", postgresql.JSONB),
        sa.column("input_contract", postgresql.JSONB),
        sa.column("output_contract", postgresql.JSONB),
        sa.column("required_permissions", postgresql.JSONB),
        sa.column("required_tools", postgresql.JSONB),
        sa.column("execution_mode", sa.String(32)),
        sa.column("risk_level", sa.String(32)),
        sa.column("approval_requirements", postgresql.JSONB),
        sa.column("evidence_expectations", postgresql.JSONB),
        sa.column("timeout_retry_hints", postgresql.JSONB),
        sa.column("idempotency_expectations", postgresql.JSONB),
        sa.column("side_effect_classification", sa.String(64)),
        sa.column("enabled", sa.Boolean()),
        sa.column("schema_version", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )

    op.bulk_insert(capabilities_table, _capability_rows(now))
    op.bulk_insert(adapters_table, _adapter_rows(now))


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM capability_adapters WHERE name IN ('gtm.lead_discovery.declarative', 'gtm.outreach_sequence.declarative')"
        )
    )
    op.execute(sa.text("DELETE FROM capabilities WHERE name IN ('gtm.lead_discovery', 'gtm.outreach_sequence')"))
