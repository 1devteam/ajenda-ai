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


def test_empty_freshness_policy_warns(tmp_path: Path, monkeypatch) -> None:
    _minimal_repo(tmp_path)
    _write(tmp_path / "docs/policies/DOCS_FRESHNESS_POLICY.md", "")
    _patch_repo(monkeypatch, tmp_path)
    issues = drift_check._check()
    assert any("missing Last reviewed metadata" in i.message for i in issues)


# existing tests remain unchanged
