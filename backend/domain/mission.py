from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base
from backend.domain.enums import MissionState

MISSION_INTAKE_METADATA_KEY = "mission_intake"
MISSION_INTAKE_SCHEMA_VERSION = 1
MISSION_PLAN_METADATA_KEY = "mission_plan"
MISSION_PLAN_SCHEMA_VERSION = 1


def utcnow() -> datetime:
    return datetime.now(UTC)


def build_mission_intake_metadata(
    *,
    success_criteria: list[dict[str, Any]],
    constraints: list[dict[str, Any]],
    operator_notes: str | None,
    context: dict[str, Any],
    priority: str,
    approval_required: bool,
    approval_expectations: list[str],
    budget_limits: dict[str, Any] | None,
    scope_limits: list[str],
    allowed_actions: list[str],
    allowed_tools: list[str],
) -> dict[str, Any]:
    return {
        MISSION_INTAKE_METADATA_KEY: {
            "schema_version": MISSION_INTAKE_SCHEMA_VERSION,
            "success_criteria": success_criteria,
            "constraints": constraints,
            "operator_notes": operator_notes,
            "context": context,
            "priority": priority,
            "approval_required": approval_required,
            "approval_expectations": approval_expectations,
            "budget_limits": budget_limits,
            "scope_limits": scope_limits,
            "allowed_actions": allowed_actions,
            "allowed_tools": allowed_tools,
        }
    }


def build_mission_plan_metadata(
    *,
    status: str,
    phases: list[dict[str, Any]],
    planning_notes: str | None,
    desired_outputs: list[str],
    capability_requirements: list[str],
    execution_strategy_hints: list[str],
    approval_gates: list[dict[str, Any]],
    operator_overrides: dict[str, Any],
    estimated_scope: dict[str, Any] | None,
    risk_annotations: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        MISSION_PLAN_METADATA_KEY: {
            "schema_version": MISSION_PLAN_SCHEMA_VERSION,
            "status": status,
            "phases": phases,
            "planning_notes": planning_notes,
            "desired_outputs": desired_outputs,
            "capability_requirements": capability_requirements,
            "execution_strategy_hints": execution_strategy_hints,
            "approval_gates": approval_gates,
            "operator_overrides": operator_overrides,
            "estimated_scope": estimated_scope,
            "risk_annotations": risk_annotations,
        }
    }


class Mission(Base):
    __tablename__ = "missions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=MissionState.PLANNED.value)
    compliance_category: Mapped[str] = mapped_column(String(64), nullable=False, default="operational")
    jurisdiction: Mapped[str] = mapped_column(String(64), nullable=False, default="US-ALL")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
