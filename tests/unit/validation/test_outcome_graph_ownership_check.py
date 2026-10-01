from __future__ import annotations

import json
from pathlib import Path

from scripts.validation.outcome_graph_ownership_check import validate_manifest

MANIFEST = Path("docs/contracts/outcome-graph-ownership.v1.json")


def test_canonical_outcome_graph_ownership_manifest_is_valid() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert validate_manifest(payload) == []


def test_ownership_manifest_rejects_authority_promotion() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload["grants_runtime_authority"] = True
    assert "grants_runtime_authority must be false" in validate_manifest(payload)


def test_ownership_manifest_rejects_missing_graph() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    del payload["graphs"]["epistemic"]
    assert any("graphs must contain exactly" in error for error in validate_manifest(payload))
