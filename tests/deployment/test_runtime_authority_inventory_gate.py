from __future__ import annotations

from pathlib import Path

CI_WORKFLOW = Path(".github/workflows/ci.yml")
COHERENCE_WORKFLOW = Path(".github/workflows/coherence-audit.yml")
PROJECT_SPEC = Path("PROJECT_SPEC.md")
AGENT_INSTRUCTIONS = Path("AGENTS.md")

COMMAND = "python scripts/validation/runtime_authority_inventory_check.py"


def test_ci_and_coherence_workflows_run_runtime_authority_inventory() -> None:
    assert COMMAND in CI_WORKFLOW.read_text(encoding="utf-8")
    assert COMMAND in COHERENCE_WORKFLOW.read_text(encoding="utf-8")


def test_runtime_authority_inventory_is_a_required_repository_gate() -> None:
    assert COMMAND in PROJECT_SPEC.read_text(encoding="utf-8")
    assert COMMAND in AGENT_INSTRUCTIONS.read_text(encoding="utf-8")
