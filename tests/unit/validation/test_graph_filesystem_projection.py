from __future__ import annotations

import importlib.util
import json
import sys
import warnings
from pathlib import Path

VALIDATION_DIR = Path(__file__).resolve().parents[3] / "scripts/validation"
if str(VALIDATION_DIR) not in sys.path:
    sys.path.insert(0, str(VALIDATION_DIR))

MODULE_PATH = VALIDATION_DIR / "graph_filesystem_projection.py"
SPEC = importlib.util.spec_from_file_location("ajenda_graph_filesystem_projection", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_projection_is_graph_backed_and_non_mutating() -> None:
    artifact = MODULE.build_projection()

    assert artifact["artifact_kind"] == "graft_filesystem_projection"
    assert artifact["role"] == "machine_interpretation"
    assert artifact["authority"] == {
        "mutates_source": False,
        "grants_execution_authority": False,
        "grants_merge_authority": False,
        "is_refactor_plan": False,
    }
    assert artifact["source_of_truth"]["graph_builder"] == "scripts/validation/build_dependency_graph.py"
    assert artifact["graph_metrics"]["node_count"] > 0
    assert artifact["graph_metrics"]["edge_count"] > 0
    assert artifact["scope"]["flat_service_file_count"] > 0
    assert artifact["scope"]["existing_anchor_package_count"] > 0
    assert artifact["candidate_files"]


def test_projection_preserves_evidence_for_every_move_candidate() -> None:
    artifact = MODULE.build_projection()

    valid_statuses = {
        "retain",
        "ambiguous",
        "candidate_requires_proof",
        "move_candidate",
    }
    for item in artifact["candidate_files"]:
        projection = item["projection"]
        assert projection["status"] in valid_statuses
        assert item["source"].startswith("backend/services/")
        assert item["source"].count("/") == 2
        assert isinstance(item["package_affinity"], list)
        assert isinstance(item["affinity_evidence"], list)
        assert "risk" in item
        if projection["status"] in {"move_candidate", "candidate_requires_proof", "ambiguous"}:
            assert projection["candidate_package"]
            assert item["package_affinity"]
            assert item["affinity_evidence"]


def test_projection_requires_post_move_graph_comparison() -> None:
    artifact = MODULE.build_projection()
    next_step = artifact["next_machine_step"]

    assert next_step["operation"] == "materialize_candidate_delta_then_rebuild_graph"
    assert "static_cycles" in next_step["required_comparison"]
    assert "top_betweenness" in next_step["required_comparison"]
    assert "top_transitive_consumers" in next_step["required_comparison"]
    assert "proof_selection" in next_step["required_comparison"]


def test_projection_exposes_ambiguous_candidates_for_machine_interpretation() -> None:
    artifact = MODULE.build_projection()
    ambiguous = [
        {
            "source": item["source"],
            "primary_node": item["primary_node"],
            "current_boundary": item["current_boundary"],
            "projection": item["projection"],
            "package_affinity": item["package_affinity"][:5],
            "risk": item["risk"],
        }
        for item in artifact["candidate_files"]
        if item["projection"]["status"] == "ambiguous"
    ]

    assert ambiguous
    warnings.warn(
        "GRAFT_AMBIGUOUS_CANDIDATES=" + json.dumps(ambiguous, sort_keys=True, separators=(",", ":")),
        stacklevel=1,
    )
