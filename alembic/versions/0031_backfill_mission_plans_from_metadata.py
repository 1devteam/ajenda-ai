"""Backfill durable mission_plans rows from legacy mission metadata.

Revision ID: 0031_backfill_mission_plans
Revises: 0030_signup_abuse_tables
Create Date: 2026-06-22

Copies missions.metadata_json['mission_plan'] into mission_plans when no
tenant-owned plan row exists yet. Legacy metadata remains read-only fallback
until a later cleanup migration removes it.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

from backend.domain.enums import MissionPlanStatus
from backend.domain.mission import (
    MISSION_PLAN_METADATA_KEY,
    build_mission_plan_contract_metadata_from_legacy_metadata,
    legacy_mission_plan_status_from_planning_status,
)

revision = "0031_backfill_mission_plans"
down_revision = "0030_signup_abuse_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            """
            SELECT m.id, m.tenant_id, m.metadata_json
            FROM missions m
            WHERE m.metadata_json ? :plan_key
              AND NOT EXISTS (
                  SELECT 1
                  FROM mission_plans mp
                  WHERE mp.mission_id = m.id
                    AND mp.tenant_id = m.tenant_id
              )
            """
        ),
        {"plan_key": MISSION_PLAN_METADATA_KEY},
    ).mappings()

    now = datetime.now(UTC)
    for row in rows:
        metadata_json = row["metadata_json"]
        if not isinstance(metadata_json, dict):
            continue
        legacy_plan = metadata_json.get(MISSION_PLAN_METADATA_KEY)
        if not isinstance(legacy_plan, dict):
            continue
        try:
            durable_metadata = build_mission_plan_contract_metadata_from_legacy_metadata(legacy_plan)
        except ValueError:
            continue
        planning_status = legacy_plan.get("planning_status")
        status = legacy_mission_plan_status_from_planning_status(
            planning_status if isinstance(planning_status, str) else MissionPlanStatus.DRAFT.value
        )
        conn.execute(
            sa.text(
                """
                INSERT INTO mission_plans (
                    id,
                    tenant_id,
                    mission_id,
                    status,
                    metadata_json,
                    schema_version,
                    created_at,
                    updated_at
                )
                VALUES (
                    :id,
                    :tenant_id,
                    :mission_id,
                    :status,
                    CAST(:metadata_json AS JSONB),
                    :schema_version,
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "id": uuid.uuid4(),
                "tenant_id": row["tenant_id"],
                "mission_id": row["id"],
                "status": status,
                "metadata_json": json.dumps(durable_metadata, sort_keys=True),
                "schema_version": durable_metadata["schema_version"],
                "created_at": now,
                "updated_at": now,
            },
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            DELETE FROM mission_plans mp
            USING missions m
            WHERE mp.mission_id = m.id
              AND mp.tenant_id = m.tenant_id
              AND m.metadata_json ? :plan_key
              AND mp.metadata_json ? 'legacy_v1'
            """
        ),
        {"plan_key": MISSION_PLAN_METADATA_KEY},
    )