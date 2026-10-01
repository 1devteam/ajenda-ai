from __future__ import annotations

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
    comparison = build_comparison(_spec(), {"status": "passed", "metrics": {"changed_files": 3}})
    assert comparison["frontier"]["grants_runtime_authority"] is False
    assert comparison["standard_graft_plus"]["changed_files"] == 3
    assert comparison["decision_boundary"]["promotion_requires_standard_graft_plus"] is True
