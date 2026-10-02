from __future__ import annotations

import json
from pathlib import Path

from scripts.validation.graft_plus_frontier import build_comparison, validate_frontier_spec


def _spec() -> dict:
    return {
        "schema_version": 1,
        "artifact_kind": "graft_plus_frontier",
        "proposal_id": "frontier-demo-v1",
        "target_outcome": "Evaluate a reversible planning experiment",
        "status": "experimental",
        "source_of_truth": "current Ajenda implementation and runtime artifacts",
        "hypotheses": ["A shadow plan can expose missing evidence before admission"],
        "candidate_paths": ["shadow_plan", "counterfactual_plan"],
        "invariants": ["tenant isolation", "ActionRegistry remains authoritative"],
        "authority_boundaries": ["planning only", "no runtime effects"],
        "experiments": [{"id": "exp-1", "rollback": "disable proposal"}],
        "promotion_criteria": ["standard GRAFT+ proof passes"],
        "rollback": {"kill_switch": "frontier proposal disable flag"},
        "grants_runtime_authority": False,
        "runtime_effects": [],
    }


def test_frontier_contract_is_non_authoritative() -> None:
    assert validate_frontier_spec(_spec()) == []


def test_frontier_rejects_authority_claims() -> None:
    spec = _spec()
    spec["grants_runtime_authority"] = True
    spec["authority_boundaries"] = ["dispatch tasks"]
    errors = validate_frontier_spec(spec)
    assert any("grants_runtime_authority" in error for error in errors)
    assert any("dispatch" in error for error in errors)


def test_side_by_side_comparison_keeps_tracks_separate() -> None:
    comparison = build_comparison(
        _spec(),
        {
            "changed_files": ["a.py", "b.py", "c.py"],
            "changed_nodes": ["a", "b"],
            "impacted_tests": ["test_a"],
            "metrics": {"changed_file_count": 3, "changed_node_count": 2, "impacted_test_count": 1},
        },
    )
    assert comparison["frontier"]["grants_runtime_authority"] is False
    assert comparison["standard_graft_plus"]["changed_file_count"] == 3
    assert comparison["standard_graft_plus"]["changed_node_count"] == 2
    assert comparison["decision_boundary"]["promotion_requires_standard_graft_plus"] is True


def _v2_spec() -> dict:
    return {
        **_spec(),
        "schema_version": 2,
        "owner": {"accountable": "product", "technical": "engineering", "review": "architecture"},
        "unknowns": ["preview latency"],
        "expected_failure_modes": ["false coverage gap"],
        "artifact_root": "artifacts/frontier/frontier-demo-v1",
        "experiments": [
            {
                "id": "exp-1",
                "success_signal": "preview finds missing evidence",
                "measurement": "compare preview and final artifacts",
                "artifact_path": "artifacts/frontier/frontier-demo-v1/exp-1.json",
                "rollback": "disable proposal",
            }
        ],
        "evidence_policy": {"required_artifacts": ["experiment-result.json"], "retention": "until superseded"},
    }


def test_v2_frontier_requires_durable_evidence_contract() -> None:
    spec = _v2_spec()
    assert validate_frontier_spec(spec) == []
    comparison = build_comparison(spec, {"graph_sha256": "abc", "metrics": {}})
    assert comparison["evidence_contract"]["durable_artifact_required"] is True
    assert comparison["frontier"]["experiment_ids"] == ["exp-1"]
    assert comparison["standard_graft_plus"]["graph_sha256"] == "abc"


def test_v2_rejects_placeholder_and_non_durable_experiment() -> None:
    spec = _v2_spec()
    spec["target_outcome"] = "Describe the future outcome"
    spec["experiments"][0]["artifact_path"] = "/tmp/result.json"
    errors = validate_frontier_spec(spec)
    assert any("placeholder" in error for error in errors)
    assert any("under artifacts/" in error for error in errors)


def test_v2_promotion_candidate_requires_evidence() -> None:
    spec = _v2_spec()
    spec["status"] = "promotion_candidate"
    errors = validate_frontier_spec(spec)
    assert any("promotion_evidence" in error for error in errors)


def test_frontier_template_is_evidence_ready() -> None:
    template = Path("docs/templates/graft-plus-frontier-spec.v2.json")
    spec = json.loads(template.read_text(encoding="utf-8"))
    assert validate_frontier_spec(spec) == []
