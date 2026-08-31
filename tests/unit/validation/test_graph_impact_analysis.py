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
            {
                "id": "fn:py:a:decide",
                "type": "python_function",
                "source": "backend/a.py",
                "decision_role": "classifies_materiality",
            },
            {"id": "py:b", "type": "python_module", "source": "backend/b.py"},
            {"id": "py:c", "type": "python_module", "source": "backend/c.py"},
            {"id": "boundary:x", "type": "security_boundary", "label": "X"},
            {
                "id": "test:tests/test_a.py",
                "type": "test_module",
                "source": "tests/test_a.py",
            },
            {
                "id": "test:tests/test_decide.py",
                "type": "test_module",
                "source": "tests/test_decide.py",
            },
            {
                "id": "test:tests/test_c.py",
                "type": "test_module",
                "source": "tests/test_c.py",
            },
        ],
        "edges": [
            {
                "from": "py:a",
                "to": "py:b",
                "type": "imports",
                "evidence": "backend/a.py",
            },
            {
                "from": "fn:py:a:decide",
                "to": "py:a",
                "type": "defined_in",
                "evidence": "backend/a.py:1",
            },
            {
                "from": "py:b",
                "to": "py:c",
                "type": "imports",
                "evidence": "backend/b.py",
            },
            {
                "from": "py:c",
                "to": "boundary:x",
                "type": "enforces",
                "evidence": "backend/c.py",
            },
            {
                "from": "test:tests/test_a.py",
                "to": "py:a",
                "type": "tests",
                "evidence": "tests/test_a.py",
            },
            {
                "from": "test:tests/test_decide.py",
                "to": "fn:py:a:decide",
                "type": "tests_function",
                "evidence": "tests/test_decide.py",
            },
            {
                "from": "test:tests/test_c.py",
                "to": "py:c",
                "type": "tests",
                "evidence": "tests/test_c.py",
            },
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

    assert {item["id"] for item in report["upstream_consumers"]} == {
        "py:a",
        "fn:py:a:decide",
    }
    assert [item["id"] for item in report["downstream_dependencies"]] == [
        "py:c",
        "boundary:x",
    ]


def test_impacted_tests_cover_changed_and_upstream_consumers_not_downstream_only() -> None:
    report = MODULE.analyze_impact(_graph(), ["backend/b.py"])

    assert {item["id"] for item in report["impacted_tests"]} == {
        "test:tests/test_a.py",
        "test:tests/test_decide.py",
    }


def test_changed_leaf_includes_its_test_and_all_upstream_consumers() -> None:
    report = MODULE.analyze_impact(_graph(), ["backend/c.py"])

    assert {item["id"] for item in report["upstream_consumers"]} == {
        "py:a",
        "fn:py:a:decide",
        "py:b",
    }
    assert {item["id"] for item in report["impacted_tests"]} == {
        "test:tests/test_a.py",
        "test:tests/test_decide.py",
        "test:tests/test_c.py",
    }


def test_semantic_prerequisite_and_invariant_are_reported() -> None:
    report = MODULE.analyze_impact(_graph(), ["backend/c.py"])

    assert [item["id"] for item in report["dependency_semantic_nodes"]] == ["boundary:x"]
    assert [item["id"] for item in report["relevant_invariants"]] == ["x-boundary"]


def test_runtime_contract_nodes_are_reported_as_semantic() -> None:
    graph = _graph()
    graph["nodes"].append(
        {
            "id": "job:runtime-contract",
            "type": "business_job",
            "source": "backend/job_catalog.py",
            "label": "Runtime contract",
        }
    )
    graph["edges"].append(
        {
            "from": "py:c",
            "to": "job:runtime-contract",
            "type": "declares",
            "evidence": "backend/c.py",
        }
    )

    report = MODULE.analyze_impact(graph, ["backend/c.py"])

    assert {item["id"] for item in report["dependency_semantic_nodes"]} == {
        "boundary:x",
        "job:runtime-contract",
    }


def test_unmapped_paths_are_preserved_for_review() -> None:
    report = MODULE.analyze_impact(_graph(), ["README.md"])

    assert report["changed_nodes"] == []
    assert report["unmapped_changed_files"] == ["README.md"]


def test_max_depth_limits_transitive_expansion() -> None:
    report = MODULE.analyze_impact(_graph(), ["backend/c.py"], max_depth=1)

    assert [item["id"] for item in report["upstream_consumers"]] == ["py:b"]


def test_node_level_impact_targets_one_function_and_direct_function_test() -> None:
    report = MODULE.analyze_node_impact(_graph(), ["fn:py:a:decide"], max_depth=1)

    assert report["changed_nodes"] == [
        {
            "id": "fn:py:a:decide",
            "type": "python_function",
            "source": "backend/a.py",
            "label": None,
            "decision_role": "classifies_materiality",
        }
    ]
    assert [item["id"] for item in report["downstream_dependencies"]] == ["py:a"]
    assert [item["id"] for item in report["impacted_tests"]] == ["test:tests/test_decide.py"]
    assert report["impacted_tests"][0]["coverage_edges"] == ["tests_function"]


def test_node_level_impact_rejects_unknown_node() -> None:
    try:
        MODULE.analyze_node_impact(_graph(), ["fn:missing"])
    except ValueError as exc:
        assert "Unknown graph node" in str(exc)
    else:
        raise AssertionError("expected unknown node to fail")
