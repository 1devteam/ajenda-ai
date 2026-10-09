"""Mission task-graph identity and fingerprint helpers."""

from __future__ import annotations

import hashlib

import json

from typing import Any

from uuid import UUID

def _task_graph_fingerprint(
    *,
    mission_id: str,
    graph_status: str | None,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    operator_notes: str | None,
) -> str:
    graph_identity = {
        "schema_version": 1,
        "mission_id": mission_id,
        "graph_status": graph_status,
        "nodes": nodes,
        "edges": edges,
        "operator_notes": operator_notes,
    }
    encoded = json.dumps(graph_identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"

def _task_graph_contract_content(task_graph: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": task_graph["schema_version"],
        "graph_status": task_graph["graph_status"],
        "nodes": task_graph["nodes"],
        "edges": task_graph["edges"],
        "metadata": task_graph["metadata"],
    }

def _task_graph_has_identity(task_graph: dict[str, Any]) -> bool:
    return (
        isinstance(task_graph.get("mission_id"), str)
        and isinstance(task_graph.get("graph_version"), int)
        and isinstance(task_graph.get("graph_fingerprint"), str)
    )

def _task_graph_contract_fingerprint(*, mission_id: str, normalized_graph: dict[str, Any]) -> str:
    graph_identity = {"mission_id": mission_id, **_task_graph_contract_content(normalized_graph)}
    encoded = json.dumps(graph_identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"

def _task_graph_with_identity(
    *, mission_id: UUID, normalized_graph: dict[str, Any], graph_version: int
) -> dict[str, Any]:
    mission_id_str = str(mission_id)
    graph_with_identity = {
        **_task_graph_contract_content(normalized_graph),
        "mission_id": mission_id_str,
        "graph_version": graph_version,
    }
    graph_with_identity["graph_fingerprint"] = _task_graph_contract_fingerprint(
        mission_id=mission_id_str, normalized_graph=graph_with_identity
    )
    return graph_with_identity

def _fingerprint_existing_task_graph(task_graph: dict[str, Any]) -> str | None:
    nodes = task_graph.get("nodes")
    edges = task_graph.get("edges")
    mission_id = task_graph.get("mission_id")
    if not isinstance(nodes, list) or not isinstance(edges, list) or not isinstance(mission_id, str):
        return None
    if not all(isinstance(node, dict) for node in nodes) or not all(isinstance(edge, dict) for edge in edges):
        return None
    return _task_graph_fingerprint(
        mission_id=mission_id,
        graph_status=task_graph.get("graph_status") if isinstance(task_graph.get("graph_status"), str) else None,
        nodes=nodes,
        edges=edges,
        operator_notes=task_graph.get("operator_notes") if isinstance(task_graph.get("operator_notes"), str) else None,
    )

def _next_task_graph_version(existing_graph: Any) -> int:
    if not isinstance(existing_graph, dict):
        return 1
    version = existing_graph.get("graph_version")
    if not isinstance(version, int) or version < 1:
        return 1
    return version + 1
