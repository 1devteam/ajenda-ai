"""Regression coverage for the public setup used by the live mission proof."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

from backend.services.operating_charter import default_operating_charter


def _load_operator_proof() -> ModuleType:
    path = Path("deploy/scripts/operator-mission-proof.py")
    spec = importlib.util.spec_from_file_location("operator_mission_proof", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_operator_proof_persists_and_verifies_charter_via_public_profile_api(monkeypatch) -> None:
    module = _load_operator_proof()
    calls: list[dict[str, Any]] = []

    def fake_request(
        method: str,
        _base: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        expected: int | tuple[int, ...] = 200,
    ) -> dict[str, Any]:
        calls.append({"method": method, "path": path, "body": body, "headers": headers, "expected": expected})
        if method == "GET":
            return {"operating_charter": {"status": "missing", "revision": 0}}
        assert method == "PUT"
        assert body is not None
        charter = body["approved_fact"]["value"]
        return {
            "operating_charter": {
                "status": "active",
                "revision": 1,
                "charter": {**charter, "revision": 1},
            }
        }

    monkeypatch.setattr(module, "request", fake_request)

    module.persist_proof_operating_charter(headers={"X-Tenant-Id": "tenant", "X-Api-Key": "proof-key"})

    assert [(call["method"], call["path"]) for call in calls] == [
        ("GET", "/v1/business-profile"),
        ("PUT", "/v1/business-profile/facts/operating_charter"),
    ]
    saved = calls[1]["body"]
    assert isinstance(saved, dict)
    assert saved["expected_charter_revision"] == 0
    assert saved["provenance_metadata"] == {"source": "operator_mission_proof"}
    assert saved["approved_fact"]["value"]["revision"] == 0


def test_operator_proof_charter_matches_the_authoritative_default_contract() -> None:
    module = _load_operator_proof()

    assert module.PROOF_OPERATING_CHARTER == default_operating_charter().to_fact_payload()
    assert "from backend." not in Path("deploy/scripts/operator-mission-proof.py").read_text(encoding="utf-8")
