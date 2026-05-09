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
MISSION_TASK_GRAPH_METADATA_KEY = "mission_task_graph"
MISSION_TASK_GRAPH_SCHEMA_VERSION = 1
MISSION_GRAPH_MATERIALIZATION_METADATA_KEY = "graph_materialization"
MISSION_GRAPH_MATERIALIZATION_SCHEMA_VERSION = 1


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
    """Build the durable metadata envelope for mission intake v1.

    Mission intake is a product-layer contract stored in structured mission
    metadata so this first block can stay additive and avoid a migration while
    preserving existing runtime queue/worker/recovery behavior.
    """
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
    planning_status: str,
    phases: list[dict[str, Any]],
    planning_notes: str | None,
    desired_outputs: list[dict[str, Any]],
    capability_requirements: list[dict[str, Any]],
    execution_strategy_hints: dict[str, Any],
    approval_gates: list[dict[str, Any]],
    operator_overrides: dict[str, Any],
    estimated_scope: dict[str, Any],
    risk_annotations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the durable metadata envelope for mission planning v1.

    Mission planning is an execution-intent contract between intake and the
    future task graph layer. It is deliberately data-only: persisting this
    envelope must not queue work, create tasks, enforce capabilities, or
    bypass runtime governance.
    """
    return {
        MISSION_PLAN_METADATA_KEY: {
            "schema_version": MISSION_PLAN_SCHEMA_VERSION,
            "planning_status": planning_status,
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


def build_mission_task_graph_metadata(
    *,
    mission_id: str,
    graph_status: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    operator_notes: str | None,
    validation_metadata: dict[str, Any],
) -> dict[str, Any]:
    """Build the durable metadata envelope for task graph contracts v1.

    Task graph contracts describe planned work structure between mission
    planning and future materialization. They are deliberately metadata-only:
    persisting this envelope must not create execution tasks, queue work, call
    runtime coordinators, or enforce capability execution behavior.
    """
    return {
        MISSION_TASK_GRAPH_METADATA_KEY: {
            "schema_version": MISSION_TASK_GRAPH_SCHEMA_VERSION,
            "mission_id": mission_id,
            "graph_status": graph_status,
            "nodes": nodes,
            "edges": edges,
            "operator_notes": operator_notes,
            "validation_metadata": validation_metadata,
        }
    }


def build_graph_materialization_metadata(
    *,
    mission_id: str,
    materialization_status: str,
    materialization_source: str,
    materialization_source_version: str,
    materialization_version: int,
    planner_provenance: dict[str, Any],
    capability_selection_provenance: list[dict[str, Any]],
    graph_validation_result: dict[str, Any],
    operator_review: dict[str, Any],
    graph_generation_metadata: dict[str, Any],
    deterministic_compilation_metadata: dict[str, Any],
    generation_notes: list[str],
    materialized_at: str,
    updated_at: str,
    graph_reference: dict[str, Any],
) -> dict[str, Any]:
    """Build the durable metadata envelope for planner-to-graph materialization v1.

    Planner-to-graph materialization contracts describe how an approved or
    reviewed mission plan becomes a validated task graph using declared
    capabilities. This envelope is deliberately metadata-only: persisting it
    must not create execution tasks, queue work, call runtime coordinators,
    dispatch workers, or execute capabilities.
    """
    return {
        MISSION_GRAPH_MATERIALIZATION_METADATA_KEY: {
            "schema_version": MISSION_GRAPH_MATERIALIZATION_SCHEMA_VERSION,
            "mission_id": mission_id,
            "materialization_status": materialization_status,
            "materialization_source": materialization_source,
            "materialization_source_version": materialization_source_version,
            "materialization_version": materialization_version,
            "planner_provenance": planner_provenance,
            "capability_selection_provenance": capability_selection_provenance,
            "graph_validation_result": graph_validation_result,
            "operator_review": operator_review,
            "graph_generation_metadata": graph_generation_metadata,
            "deterministic_compilation_metadata": deterministic_compilation_metadata,
            "generation_notes": generation_notes,
            "materialized_at": materialized_at,
            "updated_at": updated_at,
            "graph_reference": graph_reference,
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
