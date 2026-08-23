from __future__ import annotations

from scripts.validation import build_dependency_graph as MODULE


def test_graph_contains_static_and_semantic_layers() -> None:
    graph = MODULE.build_graph()

    node_ids = {node["id"] for node in graph["nodes"]}
    edge_types = {edge["type"] for edge in graph["edges"]}
    invariant_ids = {item["id"] for item in graph["invariants"]}

    assert "py:backend.main" in node_ids
    assert "boundary:tenant-db" in node_ids
    assert "service:execution-coordinator" in node_ids
    assert "imports" in edge_types
    assert "http_contract" in edge_types
    assert "tenant-isolation" in invariant_ids
    assert "runtime-secret-boundary" in invariant_ids


def test_package_relative_re_exports_are_graph_edges() -> None:
    graph = MODULE.build_graph()
    edges = {(edge["from"], edge["to"], edge["type"]) for edge in graph["edges"]}

    assert ("py:backend.workers", "py:backend.workers.worker_loop", "imports") in edges


def test_every_edge_endpoint_is_defined() -> None:
    graph = MODULE.build_graph()
    node_ids = {node["id"] for node in graph["nodes"]}

    for edge in graph["edges"]:
        assert edge["from"] in node_ids
        assert edge["to"] in node_ids


def test_metrics_cover_graph() -> None:
    graph = MODULE.build_graph()

    assert graph["metrics"]["node_count"] == len(graph["nodes"])
    assert graph["metrics"]["edge_count"] == len(graph["edges"])
    assert isinstance(graph["metrics"]["static_cycles"], list)
    assert graph["metrics"]["top_fan_in"]
    assert graph["metrics"]["top_fan_out"]


def test_invariant_statuses_are_explicit() -> None:
    graph = MODULE.build_graph()
    allowed = {
        "enforced",
        "enforced_doctrine",
        "enforced_design_boundary",
        "enforced_meta_invariant",
        "policy_drift",
    }

    assert graph["invariants"]
    for invariant in graph["invariants"]:
        assert invariant["status"] in allowed
        assert invariant["rule"].strip()
        assert invariant["sources"]
