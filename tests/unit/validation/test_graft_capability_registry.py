from __future__ import annotations

from scripts.validation.graft_capability_registry import build_machine_registry


def test_registry_preserves_core_and_external_observer_boundary() -> None:
    registry = build_machine_registry()

    providers = registry["p"]
    authorities = registry["a"]
    rows = registry["r"]
    by_provider = {providers[row[0]]: row for row in rows}

    frontier = by_provider["frontier"]
    filesystem_frontier = by_provider["filesystem_frontier"]
    canonical = by_provider["canonical_graph"]

    assert authorities[frontier[1]] == "external_observer"
    assert authorities[filesystem_frontier[1]] == "external_observer"
    assert authorities[canonical[1]] == "diagnostic"
    assert frontier[0] in registry["obs"]
    assert filesystem_frontier[0] in registry["obs"]
    assert canonical[0] in registry["core"]


def test_registry_hash_is_deterministic_and_machine_compact() -> None:
    left = build_machine_registry()
    right = build_machine_registry()

    assert left == right
    assert len(left["h"]) == 64
    assert all(isinstance(row, list) and len(row) == 4 for row in left["r"])
