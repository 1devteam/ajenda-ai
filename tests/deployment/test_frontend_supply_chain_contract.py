"""Frontend supply-chain gate contract tests."""

from __future__ import annotations

from pathlib import Path

CI_WORKFLOW = Path(".github/workflows/ci.yml")
DEPENDABOT = Path(".github/dependabot.yml")
SECURITY_WORKFLOW = Path(".github/workflows/security.yml")
DESIGN_NOTE = Path("docs/validation/frontend-supply-chain-gate.md")


def test_dependabot_scans_frontend_npm_dependency_graph() -> None:
    """Dependabot must monitor the frontend npm lockfile surface."""
    content = DEPENDABOT.read_text(encoding="utf-8")

    assert "package-ecosystem: npm" in content
    assert "directory: /frontend" in content
    assert 'prefix: "chore(frontend-deps)"' in content
    assert "- npm" in content
    assert "- frontend" in content


def test_ci_gates_frontend_install_audit_and_build() -> None:
    """CI must fail closed on frontend dependency or build regressions."""
    content = CI_WORKFLOW.read_text(encoding="utf-8")

    assert "frontend-build:" in content
    assert "name: Frontend Build & Audit" in content
    assert "uses: actions/setup-node@v4" in content
    assert 'node-version: "20"' in content
    assert "cache-dependency-path: frontend/package-lock.json" in content
    assert "working-directory: frontend" in content
    assert "npm ci" in content
    assert "npm audit" in content
    assert "npm run build" in content


def test_security_workflow_audits_frontend_npm_dependencies() -> None:
    """The scheduled security workflow must scan frontend npm dependencies."""
    content = SECURITY_WORKFLOW.read_text(encoding="utf-8")

    assert "npm-audit:" in content
    assert "name: npm-audit Frontend Dependency Scan" in content
    assert "uses: actions/setup-node@v4" in content
    assert 'node-version: "20"' in content
    assert "cache-dependency-path: frontend/package-lock.json" in content
    assert "working-directory: frontend" in content
    assert "npm ci" in content
    assert "npm audit" in content


def test_frontend_supply_chain_design_note_documents_change_control() -> None:
    """Release-gate changes must carry the required change-control notes."""
    content = DESIGN_NOTE.read_text(encoding="utf-8")

    assert "## Design note" in content
    assert "## Backward compatibility" in content
    assert "## Validation impact" in content
    assert "## Rollback strategy" in content
