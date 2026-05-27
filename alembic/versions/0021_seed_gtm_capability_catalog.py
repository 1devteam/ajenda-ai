"""Seed GTM capability catalog and declarative adapters.

Revision ID: 0021_seed_gtm_capability_catalog
Revises: 0020_expand_lifecycle_checks
Create Date: 2026-05-27
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0021_seed_gtm_capability_catalog"
down_revision = "0020_expand_lifecycle_checks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO capabilities (
                id,
                tenant_id,
                name,
                version,
                description,
                supported_task_types,
                input_schema_hints,
                output_schema_hints,
                required_permissions,
                required_tools,
                risk_level,
                approval_requirements,
                evidence_expectations,
                execution_constraints,
                enabled,
                schema_version,
                created_at,
                updated_at
            )
            VALUES
                (
                    gen_random_uuid(),
                    NULL,
                    'gtm.outbound.message_draft',
                    '1.0.0',
                    'Generates outbound message drafts without send authority.',
                    '["outbound_message_draft"]'::jsonb,
                    '{"draft_inputs": ["audience_context", "offer_context", "tone"]}'::jsonb,
                    '{"draft_outputs": ["subject", "body", "channel_variants"]}'::jsonb,
                    '["gtm.outbound.draft"]'::jsonb,
                    '["llm"]'::jsonb,
                    'medium',
                    '{"mode": "required", "requires_human_gate": true}'::jsonb,
                    '["draft_artifact", "claims_map", "policy_profile_reference"]'::jsonb,
                    '{"side_effect_class": "none", "policy_profile": "outbound_standard_v1"}'::jsonb,
                    true,
                    1,
                    now(),
                    now()
                ),
                (
                    gen_random_uuid(),
                    NULL,
                    'gtm.outbound.send_dispatch',
                    '1.0.0',
                    'Declares outbound dispatch semantics; runtime binding remains gated.',
                    '["outbound_send_dispatch"]'::jsonb,
                    '{"send_inputs": ["approved_message", "recipient", "channel_auth"]}'::jsonb,
                    '{"send_outputs": ["dispatch_receipt", "provider_reference"]}'::jsonb,
                    '["gtm.outbound.send"]'::jsonb,
                    '["channel_provider"]'::jsonb,
                    'high',
                    '{"mode": "multi_party_required", "requires_human_gate": true}'::jsonb,
                    '["approval_record", "policy_decision", "dispatch_envelope"]'::jsonb,
                    '{"side_effect_class": "external_send", "policy_profile": "outbound_high_risk_v1"}'::jsonb,
                    false,
                    1,
                    now(),
                    now()
                )
            ON CONFLICT (name, version) WHERE tenant_id IS NULL DO NOTHING
            """
        )
    )

    op.execute(
        sa.text(
            """
            INSERT INTO capability_adapters (
                id,
                tenant_id,
                name,
                version,
                capability_name,
                capability_version,
                supported_task_types,
                input_contract,
                output_contract,
                required_permissions,
                required_tools,
                execution_mode,
                risk_level,
                approval_requirements,
                evidence_expectations,
                timeout_retry_hints,
                idempotency_expectations,
                side_effect_classification,
                enabled,
                schema_version,
                created_at,
                updated_at
            )
            VALUES
                (
                    gen_random_uuid(),
                    NULL,
                    'gtm.adapter.outbound.message_draft.declarative',
                    '1.0.0',
                    'gtm.outbound.message_draft',
                    '1.0.0',
                    '["outbound_message_draft"]'::jsonb,
                    '{"contract": "draft_only"}'::jsonb,
                    '{"contract": "draft_artifact"}'::jsonb,
                    '["gtm.outbound.draft"]'::jsonb,
                    '["llm"]'::jsonb,
                    'declarative',
                    'medium',
                    '{"mode": "required"}'::jsonb,
                    '["draft_artifact", "policy_reference"]'::jsonb,
                    '{"timeout_seconds": 30, "max_retries": 1}'::jsonb,
                    '{"required": false}'::jsonb,
                    'none',
                    true,
                    1,
                    now(),
                    now()
                ),
                (
                    gen_random_uuid(),
                    NULL,
                    'gtm.adapter.outbound.send_dispatch.declarative',
                    '1.0.0',
                    'gtm.outbound.send_dispatch',
                    '1.0.0',
                    '["outbound_send_dispatch"]'::jsonb,
                    '{"contract": "approved_send_only"}'::jsonb,
                    '{"contract": "dispatch_receipt"}'::jsonb,
                    '["gtm.outbound.send"]'::jsonb,
                    '["channel_provider"]'::jsonb,
                    'declarative',
                    'high',
                    '{"mode": "multi_party_required"}'::jsonb,
                    '["approval_record", "policy_decision", "dispatch_envelope"]'::jsonb,
                    '{"timeout_seconds": 60, "max_retries": 0}'::jsonb,
                    '{"required": true, "key_source": "task_id"}'::jsonb,
                    'external_side_effect',
                    false,
                    1,
                    now(),
                    now()
                )
            ON CONFLICT (name, version) WHERE tenant_id IS NULL DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM capability_adapters
            WHERE tenant_id IS NULL
              AND (name, version) IN (
                ('gtm.adapter.outbound.message_draft.declarative', '1.0.0'),
                ('gtm.adapter.outbound.send_dispatch.declarative', '1.0.0')
              )
            """
        )
    )
    op.execute(
        sa.text(
            """
            DELETE FROM capabilities
            WHERE tenant_id IS NULL
              AND (name, version) IN (
                ('gtm.outbound.message_draft', '1.0.0'),
                ('gtm.outbound.send_dispatch', '1.0.0')
              )
            """
        )
    )
