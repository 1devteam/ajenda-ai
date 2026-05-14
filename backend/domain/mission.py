from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base
from backend.domain.enums import MissionPlanStatus, MissionState

MISSION_INTAKE_METADATA_KEY = "mission_intake"
MISSION_INTAKE_SCHEMA_VERSION = 1
MISSION_PLAN_METADATA_KEY = "mission_plan"
MISSION_PLAN_SCHEMA_VERSION = 1
MISSION_PLAN_CONTRACT_SCHEMA_VERSION = 1
MISSION_TASK_GRAPH_METADATA_KEY = "mission_task_graph"
MISSION_TASK_GRAPH_SCHEMA_VERSION = 1
MISSION_GRAPH_MATERIALIZATION_METADATA_KEY = "graph_materialization"
MISSION_GRAPH_MATERIALIZATION_SCHEMA_VERSION = 1
MISSION_RUNTIME_ADMISSION_METADATA_KEY = "runtime_admission"
MISSION_RUNTIME_ADMISSION_SCHEMA_VERSION = 1
MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY = "runtime_task_materialization"
MISSION_RUNTIME_TASK_MATERIALIZATION_SCHEMA_VERSION = 1
MISSION_RUNTIME_QUEUE_ADMISSION_METADATA_KEY = "runtime_queue_admission"
MISSION_RUNTIME_QUEUE_ADMISSION_SCHEMA_VERSION = 1
MISSION_WORKER_CLAIM_ADMISSION_METADATA_KEY = "worker_claim_admission"
MISSION_WORKER_CLAIM_ADMISSION_SCHEMA_VERSION = 1
MISSION_WORKER_START_ADMISSION_METADATA_KEY = "worker_start_admission"
MISSION_WORKER_START_ADMISSION_SCHEMA_VERSION = 1
MISSION_WORKER_RUN_ADMISSION_METADATA_KEY = "worker_run_admission"
MISSION_WORKER_RUN_ADMISSION_SCHEMA_VERSION = 1

MISSION_PLAN_ALLOWED_TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {
        (MissionPlanStatus.DRAFT.value, MissionPlanStatus.READY.value),
        (MissionPlanStatus.DRAFT.value, MissionPlanStatus.CANCELLED.value),
        (MissionPlanStatus.READY.value, MissionPlanStatus.SUPERSEDED.value),
        (MissionPlanStatus.READY.value, MissionPlanStatus.CANCELLED.value),
    }
)


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


def _json_safe_copy(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("mission plan metadata must be JSON-safe") from exc


def _normalize_string_list_field(metadata: dict[str, Any], field_name: str) -> list[str]:
    raw_value = metadata.get(field_name, [])
    if raw_value is None:
        return []
    if not isinstance(raw_value, list):
        raise ValueError(f"mission plan metadata field {field_name!r} must be a list")
    normalized: list[str] = []
    for item in raw_value:
        if not isinstance(item, str):
            raise ValueError(f"mission plan metadata field {field_name!r} must contain strings")
        item = item.strip()
        if not item:
            raise ValueError(f"mission plan metadata field {field_name!r} must not contain blank strings")
        normalized.append(item)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"mission plan metadata field {field_name!r} must contain unique strings")
    return normalized


def _normalize_planned_step(raw_step: Any) -> dict[str, Any]:
    if not isinstance(raw_step, dict):
        raise ValueError("mission plan planned_steps entries must be objects")
    allowed_fields = {"sequence", "title", "description", "depends_on", "expected_output", "metadata"}
    unknown_fields = set(raw_step) - allowed_fields
    if unknown_fields:
        raise ValueError("mission plan planned_steps entries contain unsupported fields")

    raw_sequence = raw_step.get("sequence")
    if isinstance(raw_sequence, bool) or not isinstance(raw_sequence, int) or raw_sequence < 1:
        raise ValueError("mission plan planned_steps sequence must be a positive integer")

    title = raw_step.get("title")
    description = raw_step.get("description")
    expected_output = raw_step.get("expected_output")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("mission plan planned_steps title must be a non-empty string")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("mission plan planned_steps description must be a non-empty string")
    if not isinstance(expected_output, str) or not expected_output.strip():
        raise ValueError("mission plan planned_steps expected_output must be a non-empty string")

    raw_depends_on = raw_step.get("depends_on", [])
    if raw_depends_on is None:
        raw_depends_on = []
    if not isinstance(raw_depends_on, list):
        raise ValueError("mission plan planned_steps depends_on must be a list")
    depends_on: list[int] = []
    for dependency in raw_depends_on:
        if isinstance(dependency, bool) or not isinstance(dependency, int) or dependency < 1:
            raise ValueError("mission plan planned_steps depends_on values must be positive integers")
        depends_on.append(dependency)
    if len(set(depends_on)) != len(depends_on):
        raise ValueError("mission plan planned_steps depends_on values must be unique")
    if raw_sequence in depends_on:
        raise ValueError("mission plan planned_steps cannot depend on themselves")

    raw_metadata = raw_step.get("metadata", {})
    if raw_metadata is None:
        raw_metadata = {}
    if not isinstance(raw_metadata, dict):
        raise ValueError("mission plan planned_steps metadata must be an object")

    return {
        "sequence": raw_sequence,
        "title": title.strip(),
        "description": description.strip(),
        "depends_on": depends_on,
        "expected_output": expected_output.strip(),
        "metadata": _json_safe_copy(raw_metadata),
    }


def normalize_mission_plan_contract_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Normalize persisted mission plan metadata for safe v1 reads.

    The durable plan contract currently supports only schema_version 1. This
    helper fails closed for unsupported versions, supplies deterministic v1
    defaults for optional fields, validates planned-step shape, and returns a
    JSON-safe copy without mutating the caller's dictionary.
    """
    metadata_copy = _json_safe_copy(metadata)
    if not isinstance(metadata_copy, dict):
        raise ValueError("mission plan metadata must be an object")

    schema_version = metadata_copy.get("schema_version", MISSION_PLAN_CONTRACT_SCHEMA_VERSION)
    if schema_version != MISSION_PLAN_CONTRACT_SCHEMA_VERSION:
        raise ValueError("unsupported mission plan metadata schema_version")

    raw_planned_steps = metadata_copy.get("planned_steps", [])
    if raw_planned_steps is None:
        raw_planned_steps = []
    if not isinstance(raw_planned_steps, list):
        raise ValueError("mission plan metadata field 'planned_steps' must be a list")
    planned_steps = [_normalize_planned_step(step) for step in raw_planned_steps]
    sequences = {step["sequence"] for step in planned_steps}
    if len(sequences) != len(planned_steps):
        raise ValueError("mission plan planned_steps sequence values must be unique")
    for step in planned_steps:
        missing_dependencies = [dependency for dependency in step["depends_on"] if dependency not in sequences]
        if missing_dependencies:
            raise ValueError("mission plan planned_steps dependencies must reference existing sequences")

    return {
        "schema_version": MISSION_PLAN_CONTRACT_SCHEMA_VERSION,
        "objectives": _normalize_string_list_field(metadata_copy, "objectives"),
        "constraints": _normalize_string_list_field(metadata_copy, "constraints"),
        "assumptions": _normalize_string_list_field(metadata_copy, "assumptions"),
        "acceptance_criteria": _normalize_string_list_field(metadata_copy, "acceptance_criteria"),
        "planned_steps": planned_steps,
        "risk_notes": _normalize_string_list_field(metadata_copy, "risk_notes"),
    }


def can_transition_mission_plan_status(from_status: str, to_status: str) -> bool:
    """Return whether a mission plan lifecycle status transition is allowed."""
    return (from_status, to_status) in MISSION_PLAN_ALLOWED_TRANSITIONS


def validate_mission_plan_status_transition(from_status: str, to_status: str) -> None:
    """Fail closed when a mission plan lifecycle transition is not allowed."""
    valid_statuses = {status.value for status in MissionPlanStatus}
    if from_status not in valid_statuses:
        raise ValueError(f"unknown mission plan status: {from_status}")
    if to_status not in valid_statuses:
        raise ValueError(f"unknown mission plan status: {to_status}")
    if not can_transition_mission_plan_status(from_status, to_status):
        raise ValueError(f"mission plan status transition not allowed: {from_status} -> {to_status}")


def build_mission_plan_contract_metadata(
    *,
    objectives: list[str] | None = None,
    constraints: list[str] | None = None,
    assumptions: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,
    planned_steps: list[dict[str, Any]] | None = None,
    risk_notes: list[str] | None = None,
) -> dict[str, Any]:
    """Build the durable mission planning contract metadata envelope.

    This contract is intentionally data-only. It bridges mission intake to a
    future task graph layer without creating execution tasks, enqueueing work,
    dispatching workers, or mutating runtime leases. Defaults are deterministic
    so omitted optional fields serialize identically across requests.
    """
    return normalize_mission_plan_contract_metadata(
        {
            "schema_version": MISSION_PLAN_CONTRACT_SCHEMA_VERSION,
            "objectives": list(objectives or []),
            "constraints": list(constraints or []),
            "assumptions": list(assumptions or []),
            "acceptance_criteria": list(acceptance_criteria or []),
            "planned_steps": [dict(step) for step in planned_steps or []],
            "risk_notes": list(risk_notes or []),
        }
    )


_TASK_GRAPH_ALLOWED_FIELDS = {"schema_version", "graph_status", "nodes", "edges", "metadata"}
_TASK_GRAPH_LEGACY_V1_ALLOWED_FIELDS = {
    "mission_id",
    "graph_version",
    "graph_fingerprint",
    "operator_notes",
    "validation_metadata",
}
_TASK_GRAPH_NODE_ALLOWED_FIELDS = {
    "node_key",
    "key",
    "title",
    "description",
    "capability_reference",
    "input_contract",
    "output_contract",
    "metadata",
}
_TASK_GRAPH_LEGACY_V1_NODE_ALLOWED_FIELDS = {
    "key",
    "name",
    "intended_task_type",
    "capability_references",
    "input_contract",
    "expected_output_contract",
    "risk_level",
    "approval_required",
    "execution_constraints",
    "operator_notes",
}
_TASK_GRAPH_CAPABILITY_ALLOWED_FIELDS = {"capability_id", "name", "version", "purpose"}
_TASK_GRAPH_EDGE_ALLOWED_FIELDS = {"from_node_key", "to_node_key", "dependency_type", "metadata"}
_TASK_GRAPH_LEGACY_V1_EDGE_ALLOWED_FIELDS = {"description"}


def _json_safe_contract_copy(value: Any, *, field_name: str) -> Any:
    try:
        return json.loads(json.dumps(value, allow_nan=False, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"mission task graph {field_name} must be JSON-safe") from exc


def _require_task_graph_object(value: Any, *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"mission task graph {field_name} must be an object")
    return value


def _normalize_optional_task_graph_text(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"mission task graph {field_name} must be a string or null")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"mission task graph {field_name} must be non-empty when provided")
    return normalized


def _normalize_required_task_graph_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"mission task graph {field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"mission task graph {field_name} must be non-empty")
    return normalized


def _normalize_task_graph_capability_reference(raw_reference: Any) -> dict[str, str | None]:
    reference = _require_task_graph_object(raw_reference, field_name="capability_reference")
    unknown_fields = set(reference) - _TASK_GRAPH_CAPABILITY_ALLOWED_FIELDS
    if unknown_fields:
        raise ValueError("mission task graph capability_reference contains unsupported fields")

    capability_id = _normalize_optional_task_graph_text(reference.get("capability_id"), field_name="capability_id")
    name = _normalize_optional_task_graph_text(reference.get("name"), field_name="name")
    if capability_id is None and name is None:
        raise ValueError("mission task graph capability_reference requires capability_id or name")
    return {
        "capability_id": capability_id,
        "name": name,
        "version": _normalize_optional_task_graph_text(reference.get("version"), field_name="version"),
        "purpose": _normalize_optional_task_graph_text(reference.get("purpose"), field_name="purpose"),
    }


def _legacy_v1_capability_reference(node: dict[str, Any]) -> dict[str, Any]:
    raw_references = node.get("capability_references")
    if isinstance(raw_references, list) and raw_references:
        first_reference = _require_task_graph_object(raw_references[0], field_name="capability_references entry")
        return {
            "capability_id": first_reference.get("capability_id"),
            "name": first_reference.get("name"),
            "version": first_reference.get("version"),
            "purpose": first_reference.get("purpose"),
        }
    intended_task_type = node.get("intended_task_type")
    if intended_task_type is not None:
        return {
            "capability_id": None,
            "name": intended_task_type,
            "version": None,
            "purpose": "Legacy v1 intended task type compatibility reference.",
        }
    return {"capability_id": None, "name": None, "version": None, "purpose": None}


def _normalize_task_graph_node(raw_node: Any, *, allow_legacy_v1: bool = False) -> dict[str, Any]:
    node = _require_task_graph_object(raw_node, field_name="node")
    allowed_fields = set(_TASK_GRAPH_NODE_ALLOWED_FIELDS)
    if allow_legacy_v1:
        allowed_fields.update(_TASK_GRAPH_LEGACY_V1_NODE_ALLOWED_FIELDS)
    unknown_fields = set(node) - allowed_fields
    if unknown_fields:
        raise ValueError("mission task graph node contains unsupported fields")

    raw_node_key = node.get("node_key")
    raw_key = node.get("key")
    if raw_node_key is None:
        raw_node_key = raw_key
    node_key = _normalize_required_task_graph_text(raw_node_key, field_name="node_key")
    if raw_key is not None:
        key = _normalize_required_task_graph_text(raw_key, field_name="key")
        if key != node_key:
            raise ValueError("mission task graph node_key and key must match when both are provided")

    raw_title = node.get("title")
    if raw_title is None and allow_legacy_v1:
        raw_title = node.get("name")
    title = _normalize_required_task_graph_text(raw_title, field_name="title")

    raw_description = node.get("description")
    if raw_description is None and allow_legacy_v1:
        raw_description = node.get("operator_notes") or node.get("name")
    description = _normalize_required_task_graph_text(raw_description, field_name="description")

    raw_capability_reference = node.get("capability_reference")
    if raw_capability_reference is None and allow_legacy_v1:
        raw_capability_reference = _legacy_v1_capability_reference(node)

    input_contract = _require_task_graph_object(node.get("input_contract", {}), field_name="input_contract")
    raw_output_contract = node.get("output_contract")
    if raw_output_contract is None and allow_legacy_v1:
        raw_output_contract = node.get("expected_output_contract", {})
    output_contract = _require_task_graph_object(raw_output_contract or {}, field_name="output_contract")
    metadata = _require_task_graph_object(node.get("metadata", {}), field_name="node metadata")
    normalized_metadata = _json_safe_contract_copy(metadata, field_name="node metadata")
    if allow_legacy_v1:
        legacy_metadata = {
            field_name: _json_safe_contract_copy(node[field_name], field_name=f"legacy node {field_name}")
            for field_name in sorted(_TASK_GRAPH_LEGACY_V1_NODE_ALLOWED_FIELDS)
            if field_name in node and field_name not in {"key", "name", "input_contract", "expected_output_contract"}
        }
        if legacy_metadata:
            normalized_metadata = {**normalized_metadata, "legacy_v1": legacy_metadata}

    return {
        "node_key": node_key,
        "key": node_key,
        "title": title,
        "description": description,
        "capability_reference": _normalize_task_graph_capability_reference(raw_capability_reference),
        "input_contract": _json_safe_contract_copy(input_contract, field_name="input_contract"),
        "output_contract": _json_safe_contract_copy(output_contract, field_name="output_contract"),
        "metadata": normalized_metadata,
    }


def _normalize_task_graph_edge(raw_edge: Any, *, allow_legacy_v1: bool = False) -> dict[str, Any]:
    edge = _require_task_graph_object(raw_edge, field_name="edge")
    allowed_fields = set(_TASK_GRAPH_EDGE_ALLOWED_FIELDS)
    if allow_legacy_v1:
        allowed_fields.update(_TASK_GRAPH_LEGACY_V1_EDGE_ALLOWED_FIELDS)
    unknown_fields = set(edge) - allowed_fields
    if unknown_fields:
        raise ValueError("mission task graph edge contains unsupported fields")
    metadata = _require_task_graph_object(edge.get("metadata", {}), field_name="edge metadata")
    normalized_metadata = _json_safe_contract_copy(metadata, field_name="edge metadata")
    if allow_legacy_v1 and "description" in edge:
        normalized_metadata = {
            **normalized_metadata,
            "legacy_v1": {
                "description": _json_safe_contract_copy(edge["description"], field_name="legacy edge description")
            },
        }
    return {
        "from_node_key": _normalize_required_task_graph_text(edge.get("from_node_key"), field_name="from_node_key"),
        "to_node_key": _normalize_required_task_graph_text(edge.get("to_node_key"), field_name="to_node_key"),
        "dependency_type": _normalize_required_task_graph_text(
            edge.get("dependency_type"), field_name="dependency_type"
        ),
        "metadata": normalized_metadata,
    }


def _validate_task_graph_is_dag(*, node_keys: list[str], edges: list[dict[str, Any]]) -> None:
    node_key_set = set(node_keys)
    adjacency: dict[str, list[str]] = {key: [] for key in node_keys}
    for edge in edges:
        from_node_key = edge["from_node_key"]
        to_node_key = edge["to_node_key"]
        if from_node_key not in node_key_set:
            raise ValueError("mission task graph edge source must reference an existing node_key")
        if to_node_key not in node_key_set:
            raise ValueError("mission task graph edge target must reference an existing node_key")
        if from_node_key == to_node_key:
            raise ValueError("mission task graph edges cannot point a node to itself")
        adjacency[from_node_key].append(to_node_key)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_key: str) -> None:
        if node_key in visiting:
            raise ValueError("mission task graph must be a DAG")
        if node_key in visited:
            return
        visiting.add(node_key)
        for dependent_key in adjacency[node_key]:
            visit(dependent_key)
        visiting.remove(node_key)
        visited.add(node_key)

    for node_key in node_keys:
        visit(node_key)


def normalize_mission_task_graph_contract_metadata(
    metadata: dict[str, Any], *, allow_legacy_v1: bool = False
) -> dict[str, Any]:
    """Normalize task graph contract metadata for deterministic v1 reads/writes.

    Task graph contracts are pure mission metadata. This normalizer fails closed
    on unknown fields, unsupported schema versions, invalid dependencies, cycles,
    and non-JSON-safe contracts while returning a stable JSON-safe object without
    mutating the caller's input.
    """
    metadata_copy = _json_safe_contract_copy(metadata, field_name="metadata")
    graph = _require_task_graph_object(metadata_copy, field_name="metadata")
    allowed_fields = set(_TASK_GRAPH_ALLOWED_FIELDS)
    if allow_legacy_v1:
        allowed_fields.update(_TASK_GRAPH_LEGACY_V1_ALLOWED_FIELDS)
    unknown_fields = set(graph) - allowed_fields
    if unknown_fields:
        raise ValueError("mission task graph metadata contains unsupported fields")
    if graph.get("schema_version") != MISSION_TASK_GRAPH_SCHEMA_VERSION:
        raise ValueError("unsupported mission task graph metadata schema_version")

    graph_status = graph.get("graph_status")
    if allow_legacy_v1:
        graph_status = _normalize_required_task_graph_text(graph_status, field_name="graph_status")
    elif graph_status != "draft":
        raise ValueError("mission task graph graph_status must be draft")

    raw_nodes = graph.get("nodes")
    if not isinstance(raw_nodes, list):
        raise ValueError("mission task graph nodes must be a list")
    raw_edges = graph.get("edges", [])
    if raw_edges is None:
        raw_edges = []
    if not isinstance(raw_edges, list):
        raise ValueError("mission task graph edges must be a list")

    nodes = [_normalize_task_graph_node(node, allow_legacy_v1=allow_legacy_v1) for node in raw_nodes]
    node_keys = [node["node_key"] for node in nodes]
    if len(set(node_keys)) != len(node_keys):
        raise ValueError("mission task graph node_key values must be unique")

    edges = [_normalize_task_graph_edge(edge, allow_legacy_v1=allow_legacy_v1) for edge in raw_edges]
    _validate_task_graph_is_dag(node_keys=node_keys, edges=edges)

    graph_metadata = _require_task_graph_object(graph.get("metadata", {}), field_name="graph metadata")
    normalized_graph_metadata = _json_safe_contract_copy(graph_metadata, field_name="graph metadata")
    if allow_legacy_v1:
        legacy_metadata = {
            field_name: _json_safe_contract_copy(graph[field_name], field_name=f"legacy graph {field_name}")
            for field_name in sorted(_TASK_GRAPH_LEGACY_V1_ALLOWED_FIELDS)
            if field_name in graph
        }
        if legacy_metadata:
            normalized_graph_metadata = {**normalized_graph_metadata, "legacy_v1": legacy_metadata}
    return {
        "schema_version": MISSION_TASK_GRAPH_SCHEMA_VERSION,
        "graph_status": graph_status,
        "nodes": nodes,
        "edges": edges,
        "metadata": normalized_graph_metadata,
    }


def build_mission_task_graph_contract_metadata(
    *,
    nodes: list[dict[str, Any]] | None = None,
    edges: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic task graph contract metadata object."""
    return normalize_mission_task_graph_contract_metadata(
        {
            "schema_version": MISSION_TASK_GRAPH_SCHEMA_VERSION,
            "graph_status": "draft",
            "nodes": [dict(node) for node in nodes or []],
            "edges": [dict(edge) for edge in edges or []],
            "metadata": dict(metadata or {}),
        }
    )


def mission_plan_active_statuses() -> tuple[str, ...]:
    """Return statuses that represent the one active plan slot for a mission."""
    return (MissionPlanStatus.DRAFT.value, MissionPlanStatus.READY.value)


def build_mission_task_graph_metadata(
    *,
    mission_id: str,
    graph_status: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    operator_notes: str | None,
    validation_metadata: dict[str, Any],
    graph_version: int = 1,
    graph_fingerprint: str | None = None,
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
            "graph_version": graph_version,
            "graph_fingerprint": graph_fingerprint,
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


def build_runtime_admission_metadata(
    *,
    mission_id: str,
    admission_status: str,
    admission_version: int,
    admitted_by: str,
    admitted_at: str,
    updated_at: str,
    graph_reference: dict[str, Any],
    materialization_reference: dict[str, Any],
    selected_nodes: list[dict[str, Any]],
    validation_result: dict[str, Any],
    execution_task_records: list[dict[str, Any]],
    runtime_authority: dict[str, Any],
) -> dict[str, Any]:
    """Build the durable metadata envelope for graph-to-runtime admission v1.

    Runtime admission is a governed bridge contract from a materialized mission
    task graph toward future runtime task creation. It is deliberately
    metadata-only in this implementation: persisting this envelope must not
    create execution tasks, enqueue work, call runtime coordinators, dispatch
    workers, or execute capabilities/adapters.
    """
    return {
        MISSION_RUNTIME_ADMISSION_METADATA_KEY: {
            "schema_version": MISSION_RUNTIME_ADMISSION_SCHEMA_VERSION,
            "mission_id": mission_id,
            "admission_status": admission_status,
            "admission_version": admission_version,
            "admitted_by": admitted_by,
            "admitted_at": admitted_at,
            "updated_at": updated_at,
            "graph_reference": graph_reference,
            "materialization_reference": materialization_reference,
            "selected_nodes": selected_nodes,
            "validation_result": validation_result,
            "execution_task_records": execution_task_records,
            "runtime_authority": runtime_authority,
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


class MissionPlan(Base):
    __tablename__ = "mission_plans"
    __table_args__ = (
        Index("ix_mission_plans_tenant_id", "tenant_id"),
        Index("ix_mission_plans_mission_id", "mission_id"),
        Index("ix_mission_plans_mission_tenant", "mission_id", "tenant_id"),
        Index(
            "uq_mission_plans_active_mission_tenant",
            "tenant_id",
            "mission_id",
            unique=True,
            postgresql_where=text("status IN ('draft', 'ready')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    mission_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("missions.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=MissionPlanStatus.DRAFT.value)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    schema_version: Mapped[int] = mapped_column(nullable=False, default=MISSION_PLAN_CONTRACT_SCHEMA_VERSION)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
