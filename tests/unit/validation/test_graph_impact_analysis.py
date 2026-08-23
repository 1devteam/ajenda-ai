from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

VALIDATION_DIR = Path(__file__).resolve().parents[3] / "scripts/validation"
MODULE_PATH = VALIDATION_DIR / "graph_impact_analysis.py"
sys.path.insert(0, str(VALIDATION_DIR))
SPEC = importlib.util.spec_from_file_location("ajenda_graph_impact_analysis", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _graph() -> dict:
    return {
        "nodes": [
            {"id": "py:a", "type": "python_module", "source": "backend/a.py"},
            {"id": "py:b", "type": "python_module", "source": "backend/b.py"},
            {"id": "py:c", "type": "python_module", "source": "backend/c.py"},
            {"id": "boundary:x", "type": "security_boundary", "label": "X"},
            {"id": "test:tests/test_a.py", "type": "test_module", "source": "tests/test_a.py"},
            {"id": "test:tests/test_c.py", "type": "test_module", "source": "tests/test_c.py"},
        ],
        "edges": [
            {"from": "py:a", "to": "py:b", "type": "imports", "evidence": "backend/a.py"},
            {"from": "py:b", "to": "py:c", "type": "imports", "evidence": "backend/b.py"},
            {"from": "py:c", "to": "boundary:x", "type": "enforces", "evidence": "backend/c.py"},
            {"from": "test:tests/test_a.py", "to": "py:a", "type": "tests", "evidence": "tests/test_a.py"},
            {"from": "test:tests/test_c.py", "to": "py:c", "type": "tests", "evidence": "tests/test_c.py"},
        ],
        "invariants": [
            {
                "id": "x-boundary",
                "status": "enforced",
                "rule": "X must hold.",
                "sources": ["backend/c.py"],
            }
        ],
    }


def test_reverse_traversal_finds_consumers_and_forward_finds_dependencies() -> None:
    report = MODULE.analyze_impact(_graph(), ["backend/b.py"])

    assert [item["id"] for item in report["upstream_consumers"]] == ["py:a"]
    assert [item["id"] for item in report["downstream_dependencies"]] == ["py:c", "boundary:x"]


def test_impacted_tests_cover_changed_and_upstream_consumers_not_downstream_only() -> None:
    report = MODULE.analyze_impact(_graph(), ["backend/b.py"])

    assert [item["id"] for item in report["impacted_tests"]] == ["test:tests/test_a.py"]


def test_changed_leaf_includes_its_test_and_all_upstream_consumers() -> None:
    report = MODULE.analyze_impact(_graph(), ["backend/c.py"])

    assert {item["id"] for item in report["upstream_consumers"]} == {"py:a", "py:b"}
    assert {item["id"] for item in report["impacted_tests"]} == {
        "test:tests/test_a.py",
        "test:tests/test_c.py",
    }


def test_semantic_prerequisite_and_invariant_are_reported() -> None:
    report = MODULE.analyze_impact(_graph(), ["backend/c.py"])

    assert [item["id"] for item in report["dependency_semantic_nodes"]] == ["boundary:x"]
    assert [item["id"] for item in report["relevant_invariants"]] == ["x-boundary"]


def test_unmapped_paths_are_preserved_for_review() -> None:
    report = MODULE.analyze_impact(_graph(), ["README.md"])

    assert report["changed_nodes"] == []
    assert report["unmapped_changed_files"] == ["README.md"]


def test_max_depth_limits_transitive_expansion() -> None:
    report = MODULE.analyze_impact(_graph(), ["backend/c.py"], max_depth=1)

    assert [item["id"] for item in report["upstream_consumers"]] == ["py:b"]
