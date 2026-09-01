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
    findings = {finding["id"]: finding for finding in graph["semantic_findings"]}

    assert graph["schema_version"] == "1.4"
    assert "runtime_action_selection" in SEMANTIC_NODE_TYPES
    assert nodes["selection:sales.research_context:sales.research"]["normal_role"] == "primary"
    assert nodes["selection:sales.research_context:crm.research"]["normal_role"] == "fallback"
    assert "selection:sales.research_context:web.research" not in nodes
    assert "selection:sales.research_context:web.search" not in nodes
    assert "resolver-catalog-action-drift:sales.research_context:web.search" not in findings
    assert graph["runtime_action_selection_metrics"]["resolver_only_pair_count"] == 0


