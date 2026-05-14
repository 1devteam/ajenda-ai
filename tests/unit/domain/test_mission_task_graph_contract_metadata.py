from __future__ import annotations

import copy
import math

import pytest

from backend.domain.mission import (
    build_graph_materialization_contract_metadata,
    build_mission_task_graph_contract_metadata,
    normalize_graph_materialization_contract_metadata,
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
                "capability_references": [
                    {
                        "capability_id": None,
                        "name": "crm_read",
                        "version": "1.0.0",
                        "purpose": "Read records.",
                    }
                ],
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
                "capability_references": [
                    {
                        "capability_id": "cap-analysis",
                        "name": None,
                        "version": None,
                        "purpose": None,
                    }
                ],
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

    normalized = normalize_mission_task_graph_contract_metadata(graph)

    assert normalized == graph
    assert normalized["nodes"][0]["capability_reference"]["name"] == "crm_read"
    assert normalized["nodes"][0]["capability_references"] == [normalized["nodes"][0]["capability_reference"]]


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
    assert normalized["nodes"][0]["capability_references"] == [normalized["nodes"][0]["capability_reference"]]
    assert normalized["nodes"][0]["output_contract"] == {"artifact": "signal_summary"}
    assert normalized["mission_id"] == "mission-123"
    assert normalized["graph_version"] == 7
    assert normalized["graph_fingerprint"] == "sha256:existing-graph"


def test_normalize_mission_task_graph_contract_metadata_rejects_legacy_fields_on_writes() -> None:
    graph = _valid_graph()
    graph["graph_version"] = 1

    with pytest.raises(ValueError, match="unsupported fields"):
        normalize_mission_task_graph_contract_metadata(graph)


def _valid_graph_materialization() -> dict[str, object]:
    return {
        "schema_version": 1,
        "mission_id": "mission-123",
        "materialization_status": "validated",
        "materialization_version": 1,
        "materialized_at": "2026-05-14T00:00:00+00:00",
        "updated_at": "2026-05-14T00:00:00+00:00",
        "graph_reference": {
            "mission_id": "mission-123",
            "graph_version": 3,
            "graph_fingerprint": "sha256:graph",
        },
        "planner_provenance": {"planner": "deterministic"},
        "capability_selection_provenance": [{"node_key": "collect", "capability_id": "cap-1"}],
        "graph_validation_result": {"validation_status": "valid"},
        "operator_review": {"review_status": "approved"},
        "graph_generation_metadata": {"generator": "tests"},
        "deterministic_compilation_metadata": {"compiler_name": "tests"},
        "generation_notes": ["stable"],
        "metadata": {"owner": "contracts"},
    }


def test_normalize_graph_materialization_contract_metadata_valid_contract_is_deterministic() -> None:
    materialization = _valid_graph_materialization()

    first = normalize_graph_materialization_contract_metadata(materialization)
    second = normalize_graph_materialization_contract_metadata(materialization)

    assert first == second == materialization


def test_build_graph_materialization_contract_metadata_is_deterministic() -> None:
    materialization = _valid_graph_materialization()

    first = build_graph_materialization_contract_metadata(
        mission_id="mission-123",
        materialization_status="validated",
        materialization_version=1,
        materialized_at="2026-05-14T00:00:00+00:00",
        updated_at="2026-05-14T00:00:00+00:00",
        graph_reference=materialization["graph_reference"],
        planner_provenance=materialization["planner_provenance"],
        capability_selection_provenance=materialization["capability_selection_provenance"],
        graph_validation_result=materialization["graph_validation_result"],
        operator_review=materialization["operator_review"],
        graph_generation_metadata=materialization["graph_generation_metadata"],
        deterministic_compilation_metadata=materialization["deterministic_compilation_metadata"],
        generation_notes=materialization["generation_notes"],
        metadata=materialization["metadata"],
    )
    second = build_graph_materialization_contract_metadata(
        mission_id="mission-123",
        materialization_status="validated",
        materialization_version=1,
        materialized_at="2026-05-14T00:00:00+00:00",
        updated_at="2026-05-14T00:00:00+00:00",
        graph_reference=materialization["graph_reference"],
        planner_provenance=materialization["planner_provenance"],
        capability_selection_provenance=materialization["capability_selection_provenance"],
        graph_validation_result=materialization["graph_validation_result"],
        operator_review=materialization["operator_review"],
        graph_generation_metadata=materialization["graph_generation_metadata"],
        deterministic_compilation_metadata=materialization["deterministic_compilation_metadata"],
        generation_notes=materialization["generation_notes"],
        metadata=materialization["metadata"],
    )

    assert first == second == materialization


def test_normalize_graph_materialization_contract_metadata_does_not_mutate_input() -> None:
    materialization = _valid_graph_materialization()
    original = copy.deepcopy(materialization)

    normalize_graph_materialization_contract_metadata(materialization)

    assert materialization == original


def test_normalize_graph_materialization_contract_metadata_unsupported_fields_fail() -> None:
    materialization = _valid_graph_materialization()
    materialization["materialization_source"] = "legacy"

    with pytest.raises(ValueError, match="unsupported fields"):
        normalize_graph_materialization_contract_metadata(materialization)


def test_normalize_graph_materialization_contract_metadata_unsupported_schema_version_fails() -> None:
    materialization = _valid_graph_materialization()
    materialization["schema_version"] = 2

    with pytest.raises(ValueError, match="unsupported graph materialization metadata schema_version"):
        normalize_graph_materialization_contract_metadata(materialization)


def test_normalize_graph_materialization_contract_metadata_missing_graph_reference_fields_fail() -> None:
    materialization = _valid_graph_materialization()
    del materialization["graph_reference"]["graph_fingerprint"]

    with pytest.raises(ValueError, match="missing required fields"):
        normalize_graph_materialization_contract_metadata(materialization)


def test_normalize_graph_materialization_contract_metadata_malformed_graph_reference_fails() -> None:
    materialization = _valid_graph_materialization()
    materialization["graph_reference"] = {
        "mission_id": "mission-123",
        "graph_version": "3",
        "graph_fingerprint": "sha256:graph",
    }

    with pytest.raises(ValueError, match="graph_version must be a positive integer"):
        normalize_graph_materialization_contract_metadata(materialization)


def test_normalize_graph_materialization_contract_metadata_non_json_safe_metadata_fails() -> None:
    materialization = _valid_graph_materialization()
    materialization["metadata"] = {"score": math.nan}

    with pytest.raises(ValueError, match="JSON-safe"):
        normalize_graph_materialization_contract_metadata(materialization)


def test_normalize_graph_materialization_contract_metadata_client_superseded_status_rejected() -> None:
    materialization = _valid_graph_materialization()
    materialization["materialization_status"] = "superseded"

    with pytest.raises(ValueError, match="system-only"):
        normalize_graph_materialization_contract_metadata(materialization, allow_system_status=False)
