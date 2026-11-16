"""Regression coverage for Pass 4's public proof-tenant setup."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any


def _load_pass4_proof() -> ModuleType:
    path = Path("deploy/scripts/pass4-hubspot-provider-proof.py")
    spec = importlib.util.spec_from_file_location("pass4_hubspot_provider_proof", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pass4_proof_persists_narrow_charter_through_public_profile_api(monkeypatch) -> None:
    module = _load_pass4_proof()
    calls: list[dict[str, Any]] = []

    def fake_request(
        method: str,
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
        return {"operating_charter": {"status": "active", "revision": 1, "charter": {**charter, "revision": 1}}}

    monkeypatch.setattr(module, "request", fake_request)

    module.persist_pass4_operating_charter(headers={"X-Tenant-Id": "tenant", "X-Api-Key": "proof-key"})

    assert [(call["method"], call["path"]) for call in calls] == [
        ("GET", "/v1/business-profile"),
        ("PUT", "/v1/business-profile/facts/operating_charter"),
    ]
    saved = calls[1]["body"]
    assert isinstance(saved, dict)
    assert saved["expected_charter_revision"] == 0
    assert saved["provenance_metadata"] == {"source": "pass4_hubspot_provider_proof"}
    assert saved["approved_fact"]["value"] == module.PASS4_OPERATING_CHARTER
    assert "research.observe_contacts" in module.PASS4_OPERATING_CHARTER["may_prepare"]
