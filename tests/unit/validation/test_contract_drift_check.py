from __future__ import annotations

from pathlib import Path

from scripts.validation import contract_drift_check as drift_check


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


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


def test_missing_authority_class_is_caught(tmp_path: Path, monkeypatch) -> None:
    _minimal_repo(tmp_path)
    _write(
        tmp_path / "docs/contracts/authority-ledger.v1.yaml",
        """
version: 1
authority_entries:
  - id: mission_contract
    area: mission
    source_of_truth: [backend/api/routes/mission.py]
    route_scope: [/v1/missions]
    side_effect_class: x
    allowed_side_effects: [a]
    forbidden_side_effects: [b]
    required_proofs: []
""",
    )
    _patch_repo(monkeypatch, tmp_path)
    issues = drift_check._check()
    assert any("missing required fields: authority_class" in i.message for i in issues)


def test_malformed_entries_checked_before_authority_filter(tmp_path: Path, monkeypatch) -> None:
    _minimal_repo(tmp_path)
    _write(tmp_path / "docs/contracts/authority-ledger.v1.yaml", "version: 1\nauthority_entries:\n  - bad\n")
    _patch_repo(monkeypatch, tmp_path)
    issues = drift_check._check()
    assert any("Malformed ledger entry" in i.message for i in issues)


def test_missing_readme_or_ledger_does_not_crash(tmp_path: Path, monkeypatch) -> None:
    _write(tmp_path / "docs/policies/DOCS_FRESHNESS_POLICY.md", "x\n")
    _patch_repo(monkeypatch, tmp_path)
    issues = drift_check._check()
    assert any("Missing canonical file" in i.message for i in issues)


def test_invalid_last_reviewed_date_does_not_crash(tmp_path: Path, monkeypatch) -> None:
    _minimal_repo(tmp_path)
    _write(tmp_path / "docs/policies/DOCS_FRESHNESS_POLICY.md", "**Last reviewed:** Not A Date\n")
    _patch_repo(monkeypatch, tmp_path)
    issues = drift_check._check()
    assert any("invalid Last reviewed date" in i.message for i in issues)


def test_missing_required_proof_is_warning_default(tmp_path: Path, monkeypatch) -> None:
    _minimal_repo(tmp_path)
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
    required_proofs: [tests/unit/not_exists.py]
""",
    )
    _patch_repo(monkeypatch, tmp_path)
    issues = drift_check._check()
    assert any(i.severity == "warn" and "Required proof path" in i.message for i in issues)


def test_route_drift_is_warning_default(tmp_path: Path, monkeypatch) -> None:
    _minimal_repo(tmp_path)
    _write(tmp_path / "README.md", "- `/v1/workforce/*`\n")
    _patch_repo(monkeypatch, tmp_path)
    issues = drift_check._check()
    assert any(i.severity == "warn" and "README route family missing from ledger" in i.message for i in issues)


def test_strict_baseline_turns_drift_warnings_into_failures(tmp_path: Path, monkeypatch) -> None:
    _minimal_repo(tmp_path)
    _write(tmp_path / "README.md", "- `/v1/workforce/*`\n")
    _patch_repo(monkeypatch, tmp_path)
    issues = drift_check._check(strict_baseline=True)
    assert any(i.severity == "fail" and "README route family missing from ledger" in i.message for i in issues)


def test_current_repository_default_mode_passes() -> None:
    issues = drift_check._check()
    assert not [i for i in issues if i.severity == "fail"]
