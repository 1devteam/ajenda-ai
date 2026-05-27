"""Seed declarative GTM capability and adapter records.

Revision ID: 0021_seed_gtm_capability_catalog
Revises: 0020_expand_lifecycle_checks
Create Date: 2026-05-27 00:00:00.000000
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0021_seed_gtm_capability_catalog"
down_revision = "0020_expand_lifecycle_checks"
branch_labels = None
depends_on = None


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _adapter_side_effect_classification(side_effect: str) -> str:
    if side_effect == "none":
        return "none"
    return "external_side_effect"


CAPABILITY_SEED_NAMES = (
    "gtm.lead.discovery.query_builder.v1",
    "gtm.lead.discovery.candidate_enrichment.v1",
    "gtm.outbound.send_dispatch.v1",
)

CAPABILITY_SEED_IDS = tuple(
    uuid.uuid5(uuid.NAMESPACE_URL, f"ajenda-ai:capability:{name}") for name in CAPABILITY_SEED_NAMES
)

ADAPTER_SEED_IDS = tuple(
    uuid.uuid5(uuid.NAMESPACE_URL, f"ajenda-ai:adapter:{name}:declarative") for name in CAPABILITY_SEED_NAMES
)


def upgrade() -> None:
    conn = op.get_bind()
    now = _utcnow()

    capabilities = [
        {
            "id": CAPABILITY_SEED_IDS[0],
            "name": CAPABILITY_SEED_NAMES[0],
            "description": "Lead discovery query builder for ICP-aligned search criteria.",
            "risk": "low",
            "approval": "none",
            "enabled": True,
            "side_effect": "none",
            "mission_family": "lead_discovery",
            "channels": ["web"],
            "task_types": ["gtm.lead.discovery.query_builder"],
        },
        {
            "id": CAPABILITY_SEED_IDS[1],
            "name": CAPABILITY_SEED_NAMES[1],
            "description": "Candidate enrichment with provenance-tagged fact updates.",
            "risk": "medium",
            "approval": "sample_review",
            "enabled": True,
            "side_effect": "external_write",
            "mission_family": "lead_discovery",
            "channels": ["web", "crm"],
            "task_types": ["gtm.lead.discovery.candidate_enrichment"],
        },
        {
            "id": CAPABILITY_SEED_IDS[2],
            "name": CAPABILITY_SEED_NAMES[2],
            "description": "Outbound dispatch declarative contract record only (no runtime binding).",
            "risk": "high",
            "approval": "multi_party_required",
            "enabled": False,
            "side_effect": "external_send",
            "mission_family": "outbound_sequencing",
            "channels": ["email", "linkedin"],
            "task_types": ["gtm.outbound.send_dispatch"],
        },
    ]

    capability_rows = [
        {
            "id": item["id"],
            "tenant_id": None,
            "name": item["name"],
            "version": "1.0.0",
            "description": item["description"],
            "supported_task_types": item["task_types"],
            "input_schema_hints": {"type": "object", "additionalProperties": True},
            "output_schema_hints": {"type": "object", "additionalProperties": True},
            "required_permissions": ["gtm.contract.read"],
            "required_tools": [],
            "risk_level": item["risk"],
            "approval_requirements": {
                "mode": item["approval"],
                "requires_human_gate": item["approval"] in {"required", "multi_party_required"},
            },
            "evidence_expectations": [
                "mission_id",
                "capability_id",
                "policy_profile",
                "policy_decision_reference",
            ],
            "execution_constraints": {
                "authority_class": "declarative",
                "runtime_binding": "forbidden_until_bundle_6_3",
                "mission_family": item["mission_family"],
                "channel": item["channels"],
                "side_effect_class": item["side_effect"],
            },
            "enabled": item["enabled"],
            "schema_version": 1,
            "created_at": now,
            "updated_at": now,
        }
        for item in capabilities
    ]

    capability_adapters_rows = [
        {
            "id": ADAPTER_SEED_IDS[index],
            "tenant_id": None,
            "name": f"{item['name']}.adapter",
            "version": "1.0.0",
            "capability_id": item["id"],
            "capability_name": item["name"],
            "capability_version": "1.0.0",
            "supported_task_types": item["task_types"],
            "input_contract": {"schema": "declarative", "runtime_binding": "forbidden"},
            "output_contract": {"schema": "declarative", "runtime_binding": "forbidden"},
            "required_permissions": ["gtm.contract.read"],
            "required_tools": [],
            "execution_mode": "declarative",
            "risk_level": item["risk"],
            "approval_requirements": {
                "mode": item["approval"],
                "requires_human_gate": item["approval"] in {"required", "multi_party_required"},
            },
            "evidence_expectations": ["capability_id", "adapter_id", "policy_profile"],
            "timeout_retry_hints": {"strategy": "n/a_declarative_only"},
            "idempotency_expectations": {"required": True, "reason": "future runtime safety"},
            "side_effect_classification": _adapter_side_effect_classification(item["side_effect"]),
            "enabled": item["enabled"],
            "schema_version": 1,
            "created_at": now,
            "updated_at": now,
        }
        for index, item in enumerate(capabilities)
    ]

    capability_table = sa.table(
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
    adapter_table = sa.table(
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

    op.bulk_insert(capability_table, capability_rows)
    op.bulk_insert(adapter_table, capability_adapters_rows)

    conn.execute(
        sa.text("COMMENT ON TABLE capabilities IS 'Includes global GTM declarative catalog seed records (Bundle 6.2).'")
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM capability_adapters WHERE id IN :adapter_ids").bindparams(
            sa.bindparam("adapter_ids", ADAPTER_SEED_IDS, expanding=True)
        )
    )
    conn.execute(
        sa.text("DELETE FROM capabilities WHERE id IN :capability_ids").bindparams(
            sa.bindparam("capability_ids", CAPABILITY_SEED_IDS, expanding=True)
        )
    )
