"""CI workflow contract tests for Docker-backed integration test execution."""

from __future__ import annotations

import tomllib
from pathlib import Path

CI_WORKFLOW = Path(".github/workflows/ci.yml")
PYPROJECT = Path("pyproject.toml")


def _integration_job_block() -> str:
    content = CI_WORKFLOW.read_text(encoding="utf-8")
    start = content.index("  integration-tests:")
    end = content.index("  # ─", start + len("  integration-tests:"))
    return content[start:end]


def _dev_dependencies() -> list[str]:
    project_config = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return project_config["project"]["optional-dependencies"]["dev"]


def test_integration_job_uses_testcontainers_not_fixed_service_containers() -> None:
    """Integration CI should let fixtures own Postgres/Redis lifecycle through Testcontainers."""
    block = _integration_job_block()

    assert "Verify Docker daemon for Testcontainers" in block
    assert "docker info" in block
    assert "services:" not in block
    assert "postgres:16-alpine" not in block
    assert "redis:7-alpine" not in block
    assert "alembic upgrade head" not in block


def test_ci_dev_extra_installs_testcontainers_runtime_dependencies_once() -> None:
    """CI uses pip install .[dev], so dev extras must include Docker and Testcontainers."""
    dev_dependencies = _dev_dependencies()

    docker_deps = [dep for dep in dev_dependencies if dep.partition(">=")[0] == "docker"]
    testcontainer_deps = [dep for dep in dev_dependencies if dep.partition(">=")[0] == "testcontainers[postgres,redis]"]

    assert len(docker_deps) == 1
    assert len(testcontainer_deps) == 1
