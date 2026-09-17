from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import UUID

from backend.domain.mission import (
    MISSION_GRAPH_MATERIALIZATION_METADATA_KEY,
    MISSION_TASK_GRAPH_METADATA_KEY,
)


def runtime_preview_authority_flags() -> dict[str, bool]:
    """Return authority flags for read-only runtime task preview projections."""
    return {
        "creates_execution_tasks": False,
        "enqueues_work": False,
        "dispatches_workers": False,
        "calls_executor": False,
        "calls_coordinator": False,
    }


def runtime_materialization_authority_flags() -> dict[str, bool]:
    """Return authority flags for execution task materialization contracts."""
    return {
        "creates_execution_tasks": True,
        "enqueues_work": False,
        "dispatches_workers": False,
        "calls_executor": False,
        "calls_coordinator": False,
    }


def metadata_reference(metadata: dict[str, Any] | None, key: str) -> dict[str, Any] | None:
    """Return a metadata sub-document only when it is an object."""
    value = (metadata or {}).get(key)
    if isinstance(value, dict):
        return value
    return None


def graph_matches_reference(*, task_graph: dict[str, Any], graph_reference: dict[str, Any] | None) -> bool:
    """Return whether a task graph matches a persisted graph reference."""
    graph_fingerprint = task_graph.get("graph_fingerprint")
    return isinstance(graph_reference, dict) and (
        graph_reference.get("metadata_key") == MISSION_TASK_GRAPH_METADATA_KEY
        and graph_reference.get("graph_version") == task_graph.get("graph_version")
        and graph_reference.get("graph_fingerprint") == graph_fingerprint
    )


def materialization_matches_reference(
    *, materialization: dict[str, Any], materialization_reference: dict[str, Any] | None
) -> bool:
    """Return whether graph materialization matches a persisted materialization reference."""
    if not isinstance(materialization_reference, dict):
        return False
    return (
        materialization_reference.get("metadata_key") == MISSION_GRAPH_MATERIALIZATION_METADATA_KEY
        and materialization_reference.get("materialization_status") == materialization.get("materialization_status")
        and materialization_reference.get("materialization_version") == materialization.get("materialization_version")
        and materialization_reference.get("graph_reference") == materialization.get("graph_reference")
    )


def materialization_reference_current(
    *,
    task_materialization: dict[str, Any],
    graph_reference: dict[str, Any] | None,
    materialization_reference: dict[str, Any] | None,
    admission_reference: dict[str, Any] | None,
) -> bool:
    """Return whether task materialization metadata still targets the current bridge references."""
    return (
        task_materialization.get("materialization_status") == "materialized"
        and task_materialization.get("graph_reference") == graph_reference
        and task_materialization.get("materialization_reference") == materialization_reference
        and task_materialization.get("admission_reference") == admission_reference
    )


def task_preview_dependency_keys(
    *, node_key: str, task_graph: dict[str, Any], selected_node_keys: set[str]
) -> list[str]:
    """Derive selected predecessor node keys for a preview/materialized runtime task."""
    raw_edges = task_graph.get("edges")
    edges: list[Any] = raw_edges if isinstance(raw_edges, list) else []
    dependency_keys: list[str] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        from_node_key = edge.get("from_node_key")
        to_node_key = edge.get("to_node_key")
        if to_node_key == node_key and isinstance(from_node_key, str) and from_node_key in selected_node_keys:
            dependency_keys.append(from_node_key)
    return dependency_keys


def preview_capability_reference(*, selected_node: dict[str, Any], graph_node: dict[str, Any]) -> dict[str, Any] | None:
    """Build the capability reference envelope shared by preview and materialization."""
    capability_reference: dict[str, Any] = {}
    if selected_node.get("capability_id") is not None:
        capability_reference["capability_id"] = selected_node.get("capability_id")
    raw_capability_refs = graph_node.get("capability_references")
    raw_refs: list[Any] = raw_capability_refs if isinstance(raw_capability_refs, list) else []
    if raw_refs:
        capability_reference["graph_capability_references"] = deepcopy(raw_refs)
    materialization_selection = selected_node.get("materialization_selection_reference")
    if isinstance(materialization_selection, dict):
        for key in ("capability_id", "capability_name", "capability_version"):
            value = materialization_selection.get(key)
            if value is not None and key not in capability_reference:
                capability_reference[key] = value
    return capability_reference or None


def preview_adapter_reference(selected_node: dict[str, Any]) -> dict[str, Any] | None:
    """Build the adapter reference envelope shared by preview and materialization."""
    adapter_id = selected_node.get("adapter_id")
    if adapter_id is None:
        return None
    return {"adapter_id": adapter_id}


def build_runtime_task_preview_items(*, mission_id: UUID, readiness: Any) -> list[dict[str, Any]]:
    """Project deterministic future ExecutionTask rows from a ready runtime readiness result."""
    task_graph = readiness.graph_reference or {}
    admission = readiness.admission_reference or {}
    materialization = readiness.materialization_reference or {}
    raw_selected_nodes = admission.get("selected_nodes")
    selected_nodes: list[Any] = raw_selected_nodes if isinstance(raw_selected_nodes, list) else []
    raw_graph_nodes = task_graph.get("nodes")
    graph_nodes: list[Any] = raw_graph_nodes if isinstance(raw_graph_nodes, list) else []
    nodes_by_key = {
        node.get("key"): node for node in graph_nodes if isinstance(node, dict) and isinstance(node.get("key"), str)
    }
    selected_node_keys = {
        selected_node["node_key"]
        for selected_node in selected_nodes
        if isinstance(selected_node, dict) and isinstance(selected_node.get("node_key"), str)
    }
    graph_version = task_graph.get("graph_version") if isinstance(task_graph.get("graph_version"), int) else None
    graph_fingerprint = (
        task_graph.get("graph_fingerprint") if isinstance(task_graph.get("graph_fingerprint"), str) else None
    )
    materialization_version = (
        materialization.get("materialization_version")
        if isinstance(materialization.get("materialization_version"), int)
        else None
    )
    admission_version = (
        admission.get("admission_version") if isinstance(admission.get("admission_version"), int) else None
    )

    preview_items: list[dict[str, Any]] = []
    for selected_node in selected_nodes:
        if not isinstance(selected_node, dict) or not isinstance(selected_node.get("node_key"), str):
            continue
        node_key = selected_node["node_key"]
        graph_node = nodes_by_key.get(node_key)
        if graph_node is None:
            continue
        runtime_task_type = selected_node.get("runtime_task_type") or graph_node.get("intended_task_type")
        if not isinstance(runtime_task_type, str) or not runtime_task_type.strip():
            continue
        runtime_task_type = runtime_task_type.strip()
        graph_node_name = graph_node.get("name") if isinstance(graph_node.get("name"), str) else None
        materialization_selection = selected_node.get("materialization_selection_reference")
        raw_input_contract = graph_node.get("input_contract")
        input_contract: dict[str, Any] = deepcopy(raw_input_contract) if isinstance(raw_input_contract, dict) else {}
        # Canonical v2 graphs use ``output_contract``.  ``expected_output_contract``
        # is retained only for legacy v1 graph references; dropping the canonical
        # field here would leave workers without the planner's declared handoff.
        raw_expected_output_contract = graph_node.get("output_contract")
        if raw_expected_output_contract is None:
            raw_expected_output_contract = graph_node.get("expected_output_contract")
        expected_output_contract: dict[str, Any] = (
            deepcopy(raw_expected_output_contract) if isinstance(raw_expected_output_contract, dict) else {}
        )
        raw_execution_constraints = graph_node.get("execution_constraints")
        execution_constraints: dict[str, Any] = (
            deepcopy(raw_execution_constraints) if isinstance(raw_execution_constraints, dict) else {}
        )
        raw_node_metadata = graph_node.get("metadata")
        node_metadata: dict[str, Any] = raw_node_metadata if isinstance(raw_node_metadata, dict) else {}
        if node_metadata.get("materialization_role") == "intermediate":
            expected_output_contract["materialization_role"] = "intermediate"
            expected_output_contract["allow_empty"] = node_metadata.get("allow_empty") is True
        input_bindings = node_metadata.get("input_bindings") if isinstance(node_metadata, dict) else None
        payload_preview = {
            "mission_id": mission_id,
            "graph_node_key": node_key,
            "graph_version": graph_version,
            "graph_fingerprint": graph_fingerprint,
            "materialization_version": materialization_version,
            "admission_version": admission_version,
            "runtime_task_type": runtime_task_type,
            "input_contract": input_contract,
            "expected_output_contract": expected_output_contract,
            "execution_constraints": execution_constraints,
            # Ability world-state bindings for lease-scoped ToolRuntimeAuthority rebind.
            "input_bindings": deepcopy(input_bindings) if isinstance(input_bindings, list) else [],
        }
        preview_items.append(
            {
                "preview_task_key": f"mission:{mission_id}:graph:{graph_version}:node:{node_key}:runtime-task-preview",
                "graph_node_key": node_key,
                "graph_node_name": graph_node_name,
                "runtime_task_type": runtime_task_type,
                "future_execution_task_state": "planned",
                "payload_preview": payload_preview,
                "capability_reference": preview_capability_reference(
                    selected_node=selected_node, graph_node=graph_node
                ),
                "adapter_reference": preview_adapter_reference(selected_node),
                "materialization_selection_reference": (
                    deepcopy(materialization_selection) if isinstance(materialization_selection, dict) else None
                ),
                "dependency_keys": task_preview_dependency_keys(
                    node_key=node_key, task_graph=task_graph, selected_node_keys=selected_node_keys
                ),
                "operator_notes": (
                    selected_node.get("operator_notes")
                    if isinstance(selected_node.get("operator_notes"), str)
                    else graph_node.get("operator_notes")
                    if isinstance(graph_node.get("operator_notes"), str)
                    else None
                ),
            }
        )
    return preview_items


def build_execution_task_payload(
    preview_item: Any,
) -> dict[str, Any]:
    """Build the persisted ExecutionTask metadata payload from a preview item envelope."""
    if hasattr(preview_item, "model_dump"):
        item = preview_item.model_dump(mode="json")
    else:
        item = dict(preview_item)
    payload_preview = item.get("payload_preview") if isinstance(item.get("payload_preview"), dict) else {}
    runtime_task_type = payload_preview.get("runtime_task_type")
    payload: dict[str, Any] = {
        **deepcopy(payload_preview),
        "task_type": runtime_task_type,
        "capability_reference": deepcopy(item.get("capability_reference")),
        "adapter_reference": deepcopy(item.get("adapter_reference")),
        "dependency_keys": deepcopy(item.get("dependency_keys") or []),
        "input_bindings": deepcopy(payload_preview.get("input_bindings") or item.get("input_bindings") or []),
        "materialization_selection_reference": deepcopy(item.get("materialization_selection_reference")),
        "preview_task_key": item.get("preview_task_key"),
        "graph_node_key": item.get("graph_node_key") or payload_preview.get("graph_node_key"),
    }
    if runtime_task_type == "tool.invoke":
        input_contract = payload.get("input_contract")
        if isinstance(input_contract, dict):
            tool_invocation = input_contract.get("tool_invocation")
            if isinstance(tool_invocation, dict):
                payload["tool_invocation"] = deepcopy(tool_invocation)
            execution_constraints = input_contract.get("execution_constraints")
            if not isinstance(execution_constraints, dict):
                execution_constraints = payload.get("execution_constraints")
            if not isinstance(execution_constraints, dict):
                execution_constraints = {}
            # A graph preview is not an authority source. Strip any embedded
            # grant; human review can issue one after the task exists.
            execution_constraints = dict(execution_constraints)
            execution_constraints.pop("side_effect_authorization", None)
            if execution_constraints:
                payload["execution_constraints"] = execution_constraints
                input_contract = dict(input_contract)
                input_contract["execution_constraints"] = execution_constraints
                payload["input_contract"] = input_contract
            else:
                payload.pop("execution_constraints", None)
                input_contract = dict(input_contract)
                input_contract.pop("execution_constraints", None)
                payload["input_contract"] = input_contract
            credential_reference = input_contract.get("credential_reference")
            if isinstance(credential_reference, dict) and "credential_reference" not in payload:
                payload["credential_reference"] = deepcopy(credential_reference)
    return payload


def build_runtime_task_materialization_metadata(
    *,
    mission_id: UUID,
    materialization_version: int,
    created_execution_task_ids: list[str],
    graph_reference: dict[str, Any] | None,
    materialization_reference: dict[str, Any] | None,
    admission_reference: dict[str, Any] | None,
    materialized_by: str,
    now: str,
) -> dict[str, Any]:
    """Build durable mission metadata for execution task row materialization."""
    return {
        "schema_version": 1,
        "mission_id": str(mission_id),
        "materialization_status": "materialized",
        "materialization_version": materialization_version,
        "created_execution_task_ids": created_execution_task_ids,
        "graph_reference": deepcopy(graph_reference),
        "materialization_reference": deepcopy(materialization_reference),
        "admission_reference": deepcopy(admission_reference),
        "task_count": len(created_execution_task_ids),
        "materialized_by": materialized_by,
        "materialized_at": now,
        "updated_at": now,
        "runtime_authority": runtime_materialization_authority_flags(),
    }


def supersede_runtime_task_materialization(
    *, metadata: dict[str, Any], reason: str, updated_at: str, supersession: dict[str, Any] | None = None
) -> None:
    """Mark existing runtime task materialization metadata as superseded when bridge inputs change."""
    task_materialization = metadata.get("runtime_task_materialization")
    if not isinstance(task_materialization, dict):
        return
    superseded = dict(task_materialization)
    superseded["materialization_status"] = "superseded"
    superseded["updated_at"] = updated_at
    superseded["superseded_at"] = updated_at
    superseded["superseded_reason"] = reason
    if supersession:
        superseded.update(supersession)
    metadata["runtime_task_materialization"] = superseded
