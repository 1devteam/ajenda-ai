from __future__ import annotations

import json
from pathlib import Path

from scripts.validation.graft_plus_graft1st_reconciliation_check import (
    PACKAGE_PATH,
    SIMULATION_PATH,
    validate_conformance,
)


def _mutated_package(tmp_path: Path, mutate) -> Path:  # type: ignore[no-untyped-def]
    payload = json.loads(PACKAGE_PATH.read_text(encoding="utf-8"))
    mutate(payload)
    path = tmp_path / "package.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_graft_plus_reconciles_frozen_graft1st_package_and_sources() -> None:
    report = validate_conformance()

    assert report["status"] == "passed"
    assert report["errors"] == []
    assert report["node_count"] == 35
    assert report["scenario_count"] == 5
    assert report["implementation_proof_node_count"] == 17
    assert report["status_counts"]["active_worktree"] == 0
    assert report["status_counts"]["extend"] == 16
    assert report["status_counts"]["new"] == 18


def test_graft1st_conformance_rejects_stale_worktree_status(tmp_path: Path) -> None:
    package_path = _mutated_package(
        tmp_path,
        lambda payload: payload["nodes"][0].update({"implementation_status": "active_worktree"}),
    )

    report = validate_conformance(package_path=package_path, simulation_path=SIMULATION_PATH)

    assert report["status"] == "failed"
    assert any("active_worktree" in error for error in report["errors"])


def test_graft1st_conformance_rejects_implemented_node_classified_new(tmp_path: Path) -> None:
    def mutate(payload) -> None:  # type: ignore[no-untyped-def]
        node = next(item for item in payload["nodes"] if item["node_key"] == "crm.verify_effect")
        node["implementation_status"] = "new"

    package_path = _mutated_package(tmp_path, mutate)
    report = validate_conformance(package_path=package_path, simulation_path=SIMULATION_PATH)

    assert report["status"] == "failed"
    assert "implemented node is still classified new: crm.verify_effect" in report["errors"]


def test_graft1st_conformance_rejects_non_new_node_without_proof(tmp_path: Path) -> None:
    def mutate(payload) -> None:  # type: ignore[no-untyped-def]
        node = next(item for item in payload["nodes"] if item["node_key"] == "social.observe")
        node["implementation_status"] = "extend"

    package_path = _mutated_package(tmp_path, mutate)
    report = validate_conformance(package_path=package_path, simulation_path=SIMULATION_PATH)

    assert report["status"] == "failed"
    assert "non-new nodes lack implementation proof: ['social.observe']" in report["errors"]


def test_graft1st_conformance_rejects_missing_source_proof(tmp_path: Path) -> None:
    report = validate_conformance(
        repo_root=tmp_path,
        package_path=PACKAGE_PATH,
        simulation_path=SIMULATION_PATH,
    )

    assert report["status"] == "failed"
    assert any("implementation proof source is missing" in error for error in report["errors"])
