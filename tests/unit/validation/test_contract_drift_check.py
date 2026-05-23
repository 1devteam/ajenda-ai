from __future__ import annotations

import datetime as dt
from pathlib import Path

from scripts.validation import contract_drift_check as drift_check
from scripts.validation.contract_drift_check import (
    _check,
    _parse_ledger_route_scopes,
    _parse_readme_route_families,
    _route_families_from_scopes,
)


def test_parse_readme_route_families_extracts_expected_bullets() -> None:
    content = """
- `/v1/missions/*`
- `/v1/tasks/*`
- `/v1/admin/*`
"""
    assert _parse_readme_route_families(content) == {"missions", "tasks", "admin"}


def test_parse_ledger_route_scopes_ignores_empty_scopes_and_collects_v1_routes() -> None:
    content = """
authority_entries:
  - id: runtime_startup_contract
    route_scope: []
  - id: mission_contract
    route_scope:
      - /v1/missions
      - /v1/missions/{mission_id}/plan
      - /health
"""
    scopes = _parse_ledger_route_scopes(content)
    assert "/v1/missions" in scopes
    assert "/v1/missions/{mission_id}/plan" in scopes
    assert "/health" not in scopes


def test_route_family_derivation_from_scopes() -> None:
    scopes = {"/v1/missions", "/v1/missions/{mission_id}/plan", "/v1/operations/*"}
    assert _route_families_from_scopes(scopes) == {"missions", "operations"}


def test_check_reports_missing_tier1_docs_and_route_parity_failures(tmp_path: Path, monkeypatch) -> None:
    readme = tmp_path / "README.md"
    ledger = tmp_path / "docs" / "contracts" / "authority-ledger.v1.yaml"
    policy = tmp_path / "docs" / "policies" / "DOCS_FRESHNESS_POLICY.md"
    ledger.parent.mkdir(parents=True)
    policy.parent.mkdir(parents=True)

    readme.write_text("- `/v1/missions/*`\n", encoding="utf-8")
    ledger.write_text(
        "authority_entries:\n  - id: mission_contract\n    route_scope:\n      - /v1/tasks\n",
        encoding="utf-8",
    )
    policy.write_text("**Last reviewed:** May 23, 2026\n", encoding="utf-8")

    monkeypatch.setattr(drift_check, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(drift_check, "README", readme)
    monkeypatch.setattr(drift_check, "LEDGER", ledger)
    monkeypatch.setattr(drift_check, "DOCS_FRESHNESS_POLICY", policy)

    issues = _check()
    messages = {issue.message for issue in issues if issue.severity == "fail"}
    assert any("Missing Tier-1 canonical doc:" in msg for msg in messages)
    assert any("README route inventory missing families" in msg for msg in messages)
    assert any("Authority ledger route_scope missing README route families" in msg for msg in messages)


def test_check_reports_stale_docs_freshness_warning(tmp_path: Path, monkeypatch) -> None:
    readme = tmp_path / "README.md"
    ledger = tmp_path / "docs" / "contracts" / "authority-ledger.v1.yaml"
    policy = tmp_path / "docs" / "policies" / "DOCS_FRESHNESS_POLICY.md"
    adr_index = tmp_path / "docs" / "architecture" / "ADR_INDEX.md"
    matrix = tmp_path / "docs" / "validation" / "live-runtime-matrix.md"
    proof_gate = tmp_path / "docs" / "validation" / "live-runtime-proof-release-gate.md"
    project_spec = tmp_path / "PROJECT_SPEC.md"

    for path in [ledger.parent, policy.parent, adr_index.parent, matrix.parent]:
        path.mkdir(parents=True, exist_ok=True)

    readme.write_text("- `/v1/tasks/*`\n", encoding="utf-8")
    ledger.write_text(
        "authority_entries:\n  - id: task_contract\n    route_scope:\n      - /v1/tasks\n",
        encoding="utf-8",
    )
    policy.write_text("**Last reviewed:** April 1, 2026\n", encoding="utf-8")
    adr_index.write_text("ok\n", encoding="utf-8")
    matrix.write_text("ok\n", encoding="utf-8")
    proof_gate.write_text("ok\n", encoding="utf-8")
    project_spec.write_text("ok\n", encoding="utf-8")

    monkeypatch.setattr(drift_check, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(drift_check, "README", readme)
    monkeypatch.setattr(drift_check, "LEDGER", ledger)
    monkeypatch.setattr(drift_check, "DOCS_FRESHNESS_POLICY", policy)
    monkeypatch.setattr(drift_check, "_today", lambda: dt.date(2026, 5, 23))

    issues = _check()
    warnings = [issue.message for issue in issues if issue.severity == "warn"]
    assert len(warnings) == 1
    assert "stale by Tier-2 SLA" in warnings[0]
