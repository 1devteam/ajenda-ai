from __future__ import annotations

import sys
from pathlib import Path

VALIDATION_DIR = Path(__file__).resolve().parents[3] / "scripts" / "validation"
if str(VALIDATION_DIR) not in sys.path:
    sys.path.insert(0, str(VALIDATION_DIR))

from build_dependency_graph import build_graph  # noqa: E402
from graph_impact_analysis import SEMANTIC_NODE_TYPES  # noqa: E402


def test_canonical_graph_integrates_resolver_selection_topology() -> None:
    graph = build_graph()
    nodes = {node["id"]: node for node in graph["nodes"]}
    edges = {(edge["from"], edge["to"], edge["type"]) for edge in graph["edges"]}
    findings = {finding["id"]: finding for finding in graph["semantic_findings"]}

    assert graph["schema_version"] == "1.4"
    assert "runtime_action_selection" in SEMANTIC_NODE_TYPES
    assert nodes["selection:sales.research_context:sales.research"]["normal_role"] == "primary"
    assert nodes["selection:sales.research_context:web.search"]["catalog_declared"] is False
    assert (
        "job:sales.research_context",
        "selection:sales.research_context:web.search",
        "resolver_selection",
    ) in edges
    assert (
        "selection:sales.research_context:web.search",
        "action:web.search",
        "selects_action",
    ) in edges
    assert "resolver-catalog-action-drift:sales.research_context:web.search" in findings
    assert graph["runtime_action_selection_metrics"]["resolver_only_pair_count"] == 1
