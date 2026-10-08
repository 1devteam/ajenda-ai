from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

VALIDATION_DIR = Path(__file__).resolve().parents[3] / "scripts/validation"
if str(VALIDATION_DIR) not in sys.path:
    sys.path.insert(0, str(VALIDATION_DIR))

MODULE_PATH = VALIDATION_DIR / "graph_source_topology.py"
SPEC = importlib.util.spec_from_file_location("ajenda_graph_source_topology", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


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

    artifact = MODULE.build_source_topology(graph)
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
