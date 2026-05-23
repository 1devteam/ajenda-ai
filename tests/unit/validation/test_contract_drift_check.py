from __future__ import annotations

from scripts.validation.contract_drift_check import (
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
