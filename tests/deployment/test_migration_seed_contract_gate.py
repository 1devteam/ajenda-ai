from __future__ import annotations

from pathlib import Path

CI_WORKFLOW = Path(".github/workflows/ci.yml")
PR_TEMPLATE = Path(".github/pull_request_template.md")
PROJECT_SPEC = Path("PROJECT_SPEC.md")


def test_lint_job_runs_migration_seed_contract_sentinel() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")

    assert "Migration seed contract sentinel" in workflow
    assert "python scripts/validation/migration_seed_contract_check.py" in workflow
    assert "ruff check backend/ tests/ scripts/validation/" in workflow
    assert "ruff format --check backend/ tests/ scripts/validation/" in workflow


def test_schema_seed_pr_checklist_requires_parity_and_rls_residue_proof() -> None:
    template = PR_TEMPLATE.read_text(encoding="utf-8")

    assert "Schema/data seed changes prove JSONB seed-shape parity with API/domain contracts" in template
    assert "RLS-backed seed migrations prove same-role downgrade behavior and no temporary policy residue" in template
    assert "JSONB seed-shape" in template
    assert "temporary RLS policy residue checks" in template


def test_project_spec_requires_seed_shape_and_rls_lifecycle_proof() -> None:
    spec = PROJECT_SPEC.read_text(encoding="utf-8")

    assert "Seeded JSONB data that is API-visible or domain-contract-visible" in spec
    assert "shape parity with the API/domain contract" in spec
    assert "RLS-protected seed migrations" in spec
    assert "leave no temporary policy residue" in spec
