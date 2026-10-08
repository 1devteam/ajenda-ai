from scripts.validation.graph_source_topology import build_source_topology


def test_source_topology_aggregates_direct_facts_without_refactor_judgment() -> None:
    graph = {
        "schema_version": "test",
        "nodes": [
            {"id": "a", "type": "python_module", "source": "backend/services/a.py"},
            {"id": "af", "type": "python_function", "source": "backend/services/a.py"},
            {"id": "b", "type": "python_module", "source": "backend/services/pkg/b.py"},
            {"id": "t", "type": "test_module", "source": "tests/unit/test_a.py"},
        ],
        "edges": [
            {"from": "a", "to": "b", "type": "imports"},
            {"from": "af", "to": "b", "type": "calls_function"},
            {"from": "t", "to": "a", "type": "tests"},
        ],
    }

    artifact = build_source_topology(graph)
    rows = {row["source"]: row for row in artifact["rows"]}
    row = rows["backend/services/a.py"]

    assert artifact["role"] == "factual_source_index"
    assert row["node_count"] == 2
    assert row["production_outgoing_edges"] == 2
    assert row["production_incoming_edges"] == 0
    assert row["test_incident_edges"] == 1
    assert row["relation_types"] == ["calls_function", "imports", "tests"]
    assert row["neighbor_source_count"] == 2
    assert row["neighbor_namespace_count"] == 2
    assert "score" not in row
    assert "recommendation" not in row
    assert "disposition" not in row
