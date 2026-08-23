from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

VALIDATION_DIR = Path(__file__).resolve().parents[3] / "scripts" / "validation"
if str(VALIDATION_DIR) not in sys.path:
    sys.path.insert(0, str(VALIDATION_DIR))

MODULE_PATH = VALIDATION_DIR / "graph_completeness_audit.py"
SPEC = importlib.util.spec_from_file_location("graph_completeness_audit", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

architectural_boundary = MODULE.architectural_boundary
audit_graph = MODULE.audit_graph
_betweenness = MODULE._betweenness
_semantic_reconciliation = MODULE._semantic_reconciliation


def test_architectural_boundary_classifies_major_zones():
    assert architectural_boundary({"type": "runtime", "source": "backend/main.py"}) == "runtime"
    assert (
        architectural_boundary(
            {
                "type": "python_module",
                "source": "backend/services/credentials/runtime_authority.py",
            }
        )
        == "backend:services:credentials"
    )
    assert (
        architectural_boundary(
            {
                "type": "python_module",
                "source": "services/hubspot_crm_adapter/main.py",
            }
        )
        == "standalone:hubspot_crm_adapter"
    )
    assert architectural_boundary({"type": "frontend_module", "source": "frontend/src/api/client.ts"}) == "frontend"


def test_directed_betweenness_identifies_chain_choke_point():
    node_ids = ["a", "b", "c"]
    adjacency = {"a": {"b"}, "b": {"c"}, "c": set()}

    centrality = _betweenness(node_ids, adjacency)

    assert centrality["a"] == 0.0
    assert centrality["b"] == 0.5
    assert centrality["c"] == 0.0


def test_semantic_reconciliation_uses_static_reachability_as_corroboration():
    nodes = {
        "py:a": {"id": "py:a", "type": "python_module", "source": "backend/a.py"},
        "py:b": {"id": "py:b", "type": "python_module", "source": "backend/b.py"},
        "py:c": {"id": "py:c", "type": "python_module", "source": "backend/c.py"},
        "external:x": {"id": "external:x", "type": "external_service", "label": "X"},
    }
    edges = [
        {"from": "py:a", "to": "py:b", "type": "imports", "evidence": "backend/a.py"},
        {"from": "py:b", "to": "py:c", "type": "imports", "evidence": "backend/b.py"},
        {"from": "py:a", "to": "py:c", "type": "calls", "evidence": "backend/a.py"},
        {"from": "py:c", "to": "py:a", "type": "uses", "evidence": "backend/c.py"},
        {"from": "py:c", "to": "external:x", "type": "governed_http", "evidence": "backend/c.py"},
    ]

    reconciled = _semantic_reconciliation(nodes, edges)
    by_type = {item["type"]: item["classification"] for item in reconciled}

    assert by_type["calls"] == "static-corroborated"
    assert by_type["uses"] == "semantic-only"
    assert by_type["governed_http"] == "boundary-or-external"


def test_real_graph_audit_has_integrity_and_rankings():
    report = audit_graph(MODULE.build_graph())

    assert report["production_node_count"] > 0
    assert report["production_edge_count"] > 0
    assert report["top_betweenness"]
    assert report["top_transitive_consumers"]
    assert report["boundary_matrix"]
    assert report["integrity"]["pass"] is True
    assert report["integrity"]["missing_semantic_edge_evidence"] == []
    assert report["integrity"]["missing_invariant_sources"] == []
