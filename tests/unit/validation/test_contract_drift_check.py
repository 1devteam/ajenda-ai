from __future__ import annotations

from pathlib import Path

from scripts.validation import contract_drift_check as drift_check


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _valid_architecture_map() -> str:
    sections: list[str] = ["# Mission Runtime Architecture Map\n\n## Subsystem lane contract chains\n"]
    for lane_number, title in enumerate(drift_check.REQUIRED_SUBSYSTEM_LANES, start=1):
        authority = {
            1: "`read_model`; `governed_mutation`; `runtime_authoritative`",
            2: "`governed_mutation`",
            3: "`declarative`",
            4: "`declarative`; `governed_mutation`",
            5: "`read_model`; `governed_mutation`; `runtime_authoritative`",
        }.get(lane_number, "`runtime_authoritative`" if lane_number in {7, 8, 9, 10, 11, 12} else "`read_model`")
        sections.append(f"### {lane_number}. {title}\n\n")
        for field in drift_check.REQUIRED_LANE_FIELDS:
            value = authority if field == "Authority layer(s)" else f"{field.lower()} proof"
            sections.append(f"- **{field}:** {value}\n")
        sections.append("\n")
    return "".join(sections)


def _minimal_repo(tmp_path: Path) -> None:
    _write(tmp_path / "README.md", "- `/v1/missions/*`\n")
    _write(
        tmp_path / "docs/contracts/authority-ledger.v1.yaml",
        """
version: 1
authority_entries:
  - id: mission_contract
    area: mission
    source_of_truth: [backend/api/routes/mission.py]
    route_scope: [/v1/missions]
    authority_class: governed_mutation
    side_effect_class: x
    allowed_side_effects: [a]
    forbidden_side_effects: [b]
    required_proofs: [tests/unit/api/test_mission_intake_route.py]
""",
    )
    _write(tmp_path / "docs/policies/DOCS_FRESHNESS_POLICY.md", "**Last reviewed:** May 23, 2026\n")
    _write(tmp_path / "docs/product/mission-runtime-architecture-map.md", _valid_architecture_map())
    _write(
        tmp_path / "backend/api/router.py",
        """
from backend.api.routes.mission import router as mission_router
v1.include_router(mission_router)
""",
    )
    _write(tmp_path / "backend/api/routes/mission.py", 'router = APIRouter(prefix="/v1/missions")\n')
    _write(tmp_path / "tests/unit/api/test_mission_intake_route.py", "def test_x():\n    pass\n")


def _patch_repo(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(drift_check, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(drift_check, "README", tmp_path / "README.md")
    monkeypatch.setattr(drift_check, "LEDGER", tmp_path / "docs/contracts/authority-ledger.v1.yaml")
    monkeypatch.setattr(
        drift_check,
        "DOCS_FRESHNESS_POLICY",
        tmp_path / "docs/policies/DOCS_FRESHNESS_POLICY.md",
    )
    monkeypatch.setattr(drift_check, "API_ROUTER", tmp_path / "backend/api/router.py")
    monkeypatch.setattr(
        drift_check,
        "ARCHITECTURE_MAP",
        tmp_path / "docs/product/mission-runtime-architecture-map.md",
    )


def test_empty_freshness_policy_warns(tmp_path: Path, monkeypatch) -> None:
    _minimal_repo(tmp_path)
    _write(tmp_path / "docs/policies/DOCS_FRESHNESS_POLICY.md", "")
    _patch_repo(monkeypatch, tmp_path)
    issues = drift_check._check()
    assert any("missing Last reviewed metadata" in i.message for i in issues)


def test_method_prefixed_route_scopes_contribute_route_families(tmp_path: Path, monkeypatch) -> None:
    _minimal_repo(tmp_path)
    _write(
        tmp_path / "docs/contracts/authority-ledger.v1.yaml",
        """
version: 1
authority_entries:
  - id: mission_read_contract
    area: mission read
    source_of_truth: [backend/api/routes/mission.py]
    route_scope: ["GET /v1/missions/{mission_id}/worker-run-admission"]
    authority_class: read_model
    side_effect_class: read_only
    allowed_side_effects: [read]
    forbidden_side_effects: [mutate]
    required_proofs: [tests/unit/api/test_mission_intake_route.py]
  - id: mission_mutation_contract
    area: mission mutation
    source_of_truth: [backend/api/routes/mission.py]
    route_scope: ["POST /v1/missions/{mission_id}/worker-run-admission"]
    authority_class: runtime_authoritative
    side_effect_class: dispatch
    allowed_side_effects: [dispatch]
    forbidden_side_effects: [bypass]
    required_proofs: [tests/unit/api/test_mission_intake_route.py]
""",
    )
    _patch_repo(monkeypatch, tmp_path)

    issues = drift_check._check()

    assert not any("README route family missing from ledger: missions" in issue.message for issue in issues)
    assert not any("Ledger route family missing from README: GET /v1/missions" in issue.message for issue in issues)
    assert not any("Ledger route family missing from README: POST /v1/missions" in issue.message for issue in issues)


def test_route_scope_normalization_preserves_path_only_scopes() -> None:
    assert drift_check._normalize_route_scope("/v1/missions/{mission_id}") == "/v1/missions/{mission_id}"
    assert drift_check._normalize_route_scope("GET /v1/missions/{mission_id}") == "/v1/missions/{mission_id}"
    assert drift_check._normalize_route_scope("post /v1/missions/{mission_id}") == "/v1/missions/{mission_id}"


def test_method_prefixed_scopes_parse_to_v1_route_family() -> None:
    scopes = {
        "GET /v1/missions/{mission_id}/worker-run-admission",
        "POST /v1/tasks/{task_id}",
        "/v1/auth/me",
    }

    assert drift_check._route_families_from_scopes(scopes) == {"auth", "missions", "tasks"}


def test_credential_runtime_boundary_requires_ledger_source_and_proof_paths(tmp_path: Path, monkeypatch) -> None:
    _minimal_repo(tmp_path)
    _write(
        tmp_path / "docs/contracts/authority-ledger.v1.yaml",
        """
version: 1
authority_entries:
  - id: capability_action_runtime_contract
    area: runtime
    source_of_truth: [backend/services/tools/runtime_authority.py]
    route_scope: []
    authority_class: runtime_authoritative
    side_effect_class: tenant_scoped_tool_action_execution
    allowed_side_effects: [credential references are checked]
    forbidden_side_effects: [secret leaks]
    required_proofs: [tests/unit/tools/test_tool_runtime_authority.py]
""",
    )
    _write(tmp_path / "backend/services/tools/runtime_authority.py", "")
    _write(tmp_path / "tests/unit/tools/test_tool_runtime_authority.py", "")
    _patch_repo(monkeypatch, tmp_path)

    issues = drift_check._check()

    assert any(
        issue.severity == "fail" and "Credential runtime boundary missing authority ledger" in issue.message
        for issue in issues
    )


def test_subsystem_lane_map_requires_fourteen_numbered_lanes_and_fields(tmp_path: Path, monkeypatch) -> None:
    _minimal_repo(tmp_path)
    _write(
        tmp_path / "docs/product/mission-runtime-architecture-map.md",
        """
# Mission Runtime Architecture Map

## Subsystem lane contract chains

### 1. Tenant/Auth/Security boundary

- **Purpose:** exists
- **Current status:** exists
- **Authority layer(s):** `read_model`
""",
    )
    _patch_repo(monkeypatch, tmp_path)

    issues = drift_check._check()

    assert any(
        issue.severity == "fail" and "Subsystem lane map missing lane numbers" in issue.message for issue in issues
    )
    assert any(
        issue.severity == "fail" and "missing required production-grade fields" in issue.message for issue in issues
    )


def test_subsystem_lane_map_rejects_unsupported_authority_layer() -> None:
    architecture_text = _valid_architecture_map().replace("`governed_mutation`", "`superuser_runtime`", 1)

    issues = drift_check._check_subsystem_lane_contracts(architecture_text)

    assert any("unsupported authority layer" in issue.message for issue in issues)
