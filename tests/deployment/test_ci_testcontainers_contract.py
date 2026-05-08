"""CI workflow contract tests for Docker-backed integration test execution."""

from __future__ import annotations

from pathlib import Path

CI_WORKFLOW = Path(".github/workflows/ci.yml")


def _integration_job_block() -> str:
    content = CI_WORKFLOW.read_text(encoding="utf-8")
    start = content.index("  integration-tests:")
    end = content.index("  # ─", start + len("  integration-tests:"))
    return content[start:end]


def test_integration_job_uses_testcontainers_not_fixed_service_containers() -> None:
    """Integration CI should let fixtures own Postgres/Redis lifecycle through Testcontainers."""
    block = _integration_job_block()

    assert "Verify Docker daemon for Testcontainers" in block
    assert "docker info" in block
    assert "services:" not in block
    assert "postgres:16-alpine" not in block
    assert "redis:7-alpine" not in block
    assert "alembic upgrade head" not in block
