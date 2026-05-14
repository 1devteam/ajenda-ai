from __future__ import annotations

import copy
import json
from datetime import datetime

import pytest

from backend.domain.mission import (
    MISSION_TASK_GRAPH_SCHEMA_VERSION,
    MissionTaskGraph,
    TaskGraphEdge,
    TaskGraphNode,
    build_mission_task_graph_contract_metadata,
    normalize_mission_task_graph_contract_metadata,
)


def _valid_graph() -> dict[str, object]:
    return {
        "schema_version": MISSION_TASK_GRAPH_SCHEMA_VERSION,
        "nodes": [
            {
                "node_key": "collect-signals",
                "title": "Collect signals",
                "description": "Read approved CRM fields.",
                "capability_reference": "crm_read",
                "input_contract": {"source": "crm"},
                "output_contract": {"artifact": "signal_summary"},
                "metadata": {"read_only": True},
            },
            {
                "node_key": "draft-recommendations",
                "title": "Draft recommendations",
                "description": "Prepare recommendations from the signal summary.",
                "capability_reference": {"name": "analysis", "version": "1"},
                "input_contract": {"requires": "signal_summary"},
                "output_contract": {"artifact": "recommendation_set"},
                "metadata": {"approval_required": True},
            },
        ],
        "edges": [
            {
                "from_node_key": "collect-signals",
                "to_node_key": "draft-recommendations",
                "metadata": {"reason": "recommendations need signals"},
            }
        ],
    }


def test_valid_graph_is_normalized_without_mutating_input() -> None:
    graph = _valid_graph()
    original = copy.deepcopy(graph)

    normalized = normalize_mission_task_graph_contract_metadata(graph)  # type: ignore[arg-type]

    assert graph == original
    assert normalized == original
    assert json.loads(json.dumps(normalized)) == normalized


def test_task_graph_dataclass_container_serializes_to_valid_contract() -> None:
    graph = MissionTaskGraph(
        nodes=[
            TaskGraphNode(
                node_key="collect-signals",
                title="Collect signals",
                description="Read approved CRM fields.",
                capability_reference="crm_read",
                input_contract={"source": "crm"},
                output_contract={"artifact": "signal_summary"},
                metadata={"read_only": True},
            )
        ],
        edges=[],
    )

    assert TaskGraphEdge(
        from_node_key="collect-signals", to_node_key="draft", metadata={"reason": "ready"}
    ).to_metadata() == {
        "from_node_key": "collect-signals",
        "to_node_key": "draft",
        "metadata": {"reason": "ready"},
    }
    assert graph.to_metadata() == {
        "schema_version": 1,
        "nodes": [
            {
                "node_key": "collect-signals",
                "title": "Collect signals",
                "description": "Read approved CRM fields.",
                "capability_reference": "crm_read",
                "input_contract": {"source": "crm"},
                "output_contract": {"artifact": "signal_summary"},
                "metadata": {"read_only": True},
            }
        ],
        "edges": [],
    }


def test_duplicate_node_keys_rejected() -> None:
    graph = _valid_graph()
    graph["nodes"][1]["node_key"] = "collect-signals"  # type: ignore[index]

    with pytest.raises(ValueError, match="unique"):
        normalize_mission_task_graph_contract_metadata(graph)  # type: ignore[arg-type]


def test_missing_dependency_rejected() -> None:
    graph = _valid_graph()
    graph["edges"] = [{"from_node_key": "collect-signals", "to_node_key": "missing", "metadata": {}}]

    with pytest.raises(ValueError, match="existing node_keys"):
        normalize_mission_task_graph_contract_metadata(graph)  # type: ignore[arg-type]


def test_self_dependency_rejected() -> None:
    graph = _valid_graph()
    graph["edges"] = [{"from_node_key": "collect-signals", "to_node_key": "collect-signals", "metadata": {}}]

    with pytest.raises(ValueError, match="self-depend"):
        normalize_mission_task_graph_contract_metadata(graph)  # type: ignore[arg-type]


def test_cycle_detection_enforced() -> None:
    graph = _valid_graph()
    graph["edges"] = [
        {"from_node_key": "collect-signals", "to_node_key": "draft-recommendations", "metadata": {}},
        {"from_node_key": "draft-recommendations", "to_node_key": "collect-signals", "metadata": {}},
    ]

    with pytest.raises(ValueError, match="acyclic"):
        normalize_mission_task_graph_contract_metadata(graph)  # type: ignore[arg-type]


def test_json_safety_enforced() -> None:
    graph = _valid_graph()
    graph["nodes"][0]["metadata"] = {"created_at": datetime(2026, 5, 14)}  # type: ignore[index]

    with pytest.raises(ValueError, match="JSON-safe"):
        normalize_mission_task_graph_contract_metadata(graph)  # type: ignore[arg-type]


def test_builder_enforces_schema_version_and_deterministic_defaults() -> None:
    graph = _valid_graph()
    metadata = build_mission_task_graph_contract_metadata(nodes=graph["nodes"], edges=graph["edges"])  # type: ignore[arg-type]

    assert metadata["schema_version"] == MISSION_TASK_GRAPH_SCHEMA_VERSION
    assert metadata == normalize_mission_task_graph_contract_metadata(metadata)

    with pytest.raises(ValueError, match="non-empty list"):
        build_mission_task_graph_contract_metadata()
