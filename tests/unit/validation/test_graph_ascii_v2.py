from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

VALIDATION_DIR = Path(__file__).resolve().parents[3] / "scripts/validation"
if str(VALIDATION_DIR) not in sys.path:
    sys.path.insert(0, str(VALIDATION_DIR))

MODULE_PATH = VALIDATION_DIR / "graph_ascii_v2.py"
SPEC = importlib.util.spec_from_file_location("ajenda_graph_ascii_v2", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)



def test_ascii_v2_round_trips_topology_with_source_dictionary() -> None:
    graph = {
        "schema_version": "test",
        "nodes": [
            {"id": "py:a", "type": "python_module", "source": "backend/services/a.py"},
            {"id": "fn:a:f", "type": "python_function", "source": "backend/services/a.py"},
            {"id": "py:b", "type": "python_module", "source": "backend/services/b.py"},
        ],
        "edges": [
            {"from": "py:a", "to": "py:b", "type": "imports", "evidence": "backend/services/a.py"},
            {"from": "fn:a:f", "to": "py:b", "type": "calls_function", "evidence": "backend/services/a.py"},
        ],
    }

    encoded = MODULE.encode_graph_ascii_v2(graph)
    decoded = MODULE.decode_graph_ascii_v2(encoded)

    assert encoded.isascii()
    assert encoded.startswith("G2|")
    assert encoded.count("backend/services/a.py") == 1
    assert decoded["direction"] == "c>d"
    assert decoded["nodes"] == [
        {"id": "fn:a:f", "type": "python_function", "source": "backend/services/a.py"},
        {"id": "py:a", "type": "python_module", "source": "backend/services/a.py"},
        {"id": "py:b", "type": "python_module", "source": "backend/services/b.py"},
    ]
    assert decoded["edges"] == [
        {"from": "fn:a:f", "to": "py:b", "type": "calls_function"},
        {"from": "py:a", "to": "py:b", "type": "imports"},
    ]


def test_ascii_v2_keeps_residual_facts_out_of_fast_topology() -> None:
    graph = {
        "nodes": [{"id": "a", "type": "runtime", "source": "backend/a.py"}],
        "edges": [],
        "semantic_findings": [{"id": "finding:1", "summary": "not duplicated"}],
        "invariants": [{"id": "inv:1"}],
    }

    encoded = MODULE.encode_graph_ascii_v2(graph)

    assert "finding:1" not in encoded
    assert "inv:1" not in encoded
