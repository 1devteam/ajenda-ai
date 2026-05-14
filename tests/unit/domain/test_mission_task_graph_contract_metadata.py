from __future__ import annotations

import copy
import math

import pytest

from backend.domain.mission import (
    build_mission_task_graph_contract_metadata,
    normalize_mission_task_graph_contract_metadata,
)


def _valid_graph() -> dict[str, object]:
    return {
        "schema_version": 1,
        "graph_status": "draft",
        "nodes": [
            {
                "node_key": "collect-signals",
                "key": "collect-signals",
                "title": "Collect signals",
                "description": "Read approved CRM records.",
                "capability_reference": {
                    "capability_id": None,
                    "name": "crm_read",
                    "version": "1.0.0",
                    "purpose": "Read records.",
                },
                "input_contract": {"sources": ["crm"]},
                "output_contract": {"artifact": "signal_summary"},
                "metadata": {"read_only": True},
            },
            {
                "node_key": "draft-recommendations",
                "key": "draft-recommendations",
                "title": "Draft recommendations",
                "description": "Prepare recommendations.",
                "capability_reference": {
                    "capability_id": "cap-analysis",
                    "name": None,
                    "version": None,
                    "purpose": None,
                },
                "input_contract": {"requires": "signal_summary"},
                "output_contract": {"artifact": "recommendations"},
                "metadata": {},
            },
        ],
        "edges": [
            {
                "from_node_key": "collect-signals",
                "to_node_key": "draft-recommendations",
                "dependency_type": "depends_on",
                "metadata": {},
            }
        ],
        "metadata": {"owner": "planning"},
    }


def test_normalize_mission_task_graph_contract_metadata_valid_graph_passes() -> None:
    graph = _valid_graph()

    assert normalize_mission_task_graph_contract_metadata(graph) == graph


def test_build_mission_task_graph_contract_metadata_is_deterministic_and_json_safe() -> None:
    graph = _valid_graph()

    first = build_mission_task_graph_contract_metadata(
        nodes=graph["nodes"], edges=graph["edges"], metadata=graph["metadata"]
    )
    second = build_mission_task_graph_contract_metadata(
        nodes=graph["nodes"], edges=graph["edges"], metadata=graph["metadata"]
    )

    assert first == second == graph


def test_normalize_mission_task_graph_contract_metadata_does_not_mutate_input() -> None:
    graph = _valid_graph()
    original = copy.deepcopy(graph)

    normalize_mission_task_graph_contract_metadata(graph)

    assert graph == original


def test_normalize_mission_task_graph_contract_metadata_duplicate_node_key_fails() -> None:
    graph = _valid_graph()
    graph["nodes"][1]["node_key"] = "collect-signals"
    graph["nodes"][1]["key"] = "collect-signals"

    with pytest.raises(ValueError, match="node_key values must be unique"):
        normalize_mission_task_graph_contract_metadata(graph)


def test_normalize_mission_task_graph_contract_metadata_missing_node_reference_fails() -> None:
    graph = _valid_graph()
    graph["edges"][0]["to_node_key"] = "missing"

    with pytest.raises(ValueError, match="edge target must reference"):
        normalize_mission_task_graph_contract_metadata(graph)


def test_normalize_mission_task_graph_contract_metadata_self_edge_fails() -> None:
    graph = _valid_graph()
    graph["edges"][0]["to_node_key"] = "collect-signals"

    with pytest.raises(ValueError, match="cannot point a node to itself"):
        normalize_mission_task_graph_contract_metadata(graph)


def test_normalize_mission_task_graph_contract_metadata_cycle_fails() -> None:
    graph = _valid_graph()
    graph["edges"].append(
        {
            "from_node_key": "draft-recommendations",
            "to_node_key": "collect-signals",
            "dependency_type": "depends_on",
            "metadata": {},
        }
    )

    with pytest.raises(ValueError, match="must be a DAG"):
        normalize_mission_task_graph_contract_metadata(graph)


def test_normalize_mission_task_graph_contract_metadata_json_unsafe_fails() -> None:
    graph = _valid_graph()
    graph["nodes"][0]["input_contract"] = {"score": math.nan}

    with pytest.raises(ValueError, match="JSON-safe"):
        normalize_mission_task_graph_contract_metadata(graph)


def test_normalize_mission_task_graph_contract_metadata_unsupported_schema_version_fails() -> None:
    graph = _valid_graph()
    graph["schema_version"] = 2

    with pytest.raises(ValueError, match="unsupported mission task graph metadata schema_version"):
        normalize_mission_task_graph_contract_metadata(graph)


def test_normalize_mission_task_graph_contract_metadata_unsupported_fields_fail() -> None:
    graph = _valid_graph()
    graph["graph_version"] = 1

    with pytest.raises(ValueError, match="unsupported fields"):
        normalize_mission_task_graph_contract_metadata(graph)


def test_normalize_mission_task_graph_contract_metadata_accepts_key_without_node_key() -> None:
    graph = _valid_graph()
    for node in graph["nodes"]:
        node.pop("node_key")

    normalized = normalize_mission_task_graph_contract_metadata(graph)

    assert normalized["nodes"][0]["node_key"] == "collect-signals"
    assert normalized["nodes"][0]["key"] == "collect-signals"


def test_normalize_mission_task_graph_contract_metadata_rejects_mismatched_node_key_and_key() -> None:
    graph = _valid_graph()
    graph["nodes"][0]["key"] = "different"

    with pytest.raises(ValueError, match="node_key and key must match"):
        normalize_mission_task_graph_contract_metadata(graph)


def test_normalize_mission_task_graph_contract_metadata_adapts_legacy_v1_graph() -> None:
    legacy_graph = {
        "schema_version": 1,
        "mission_id": "mission-123",
        "graph_status": "approved",
        "graph_version": 7,
        "graph_fingerprint": "sha256:existing-graph",
        "nodes": [
            {
                "key": "collect-signals",
                "name": "Collect approved signals",
                "intended_task_type": "crm_research",
                "capability_references": [{"name": "crm_read", "version": "1.0.0"}],
                "input_contract": {"sources": ["crm"]},
                "expected_output_contract": {"artifact": "signal_summary"},
                "risk_level": "low",
                "approval_required": False,
                "execution_constraints": {"read_only": True},
                "operator_notes": "Use tenant-approved CRM fields only.",
            }
        ],
        "edges": [],
        "operator_notes": "Legacy graph.",
        "validation_metadata": {"validation_status": "valid"},
    }

    normalized = normalize_mission_task_graph_contract_metadata(legacy_graph, allow_legacy_v1=True)

    assert normalized["graph_status"] == "approved"
    assert normalized["nodes"][0]["node_key"] == "collect-signals"
    assert normalized["nodes"][0]["key"] == "collect-signals"
    assert normalized["nodes"][0]["title"] == "Collect approved signals"
    assert normalized["nodes"][0]["capability_reference"]["name"] == "crm_read"
    assert normalized["nodes"][0]["output_contract"] == {"artifact": "signal_summary"}
    assert normalized["metadata"]["legacy_v1"]["graph_version"] == 7
    assert normalized["metadata"]["legacy_v1"]["graph_fingerprint"] == "sha256:existing-graph"


def test_normalize_mission_task_graph_contract_metadata_rejects_legacy_fields_on_writes() -> None:
    graph = _valid_graph()
    graph["graph_version"] = 1

    with pytest.raises(ValueError, match="unsupported fields"):
        normalize_mission_task_graph_contract_metadata(graph)
