"""Drift guards for release identity and immutable version publication."""

from __future__ import annotations

from pathlib import Path

RELEASE_WORKFLOW = Path(".github/workflows/release.yml")
PYPROJECT = Path("pyproject.toml")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_release_workflow_only_publishes_version_tags_for_new_git_tags() -> None:
    workflow = _read(RELEASE_WORKFLOW)

    assert "created=false" in workflow
    assert "created=true" in workflow
    assert "TAG_CREATED" in workflow
    assert "needs.tag.outputs.created == 'true'" in workflow
    assert "version image tags will not be rewritten" in workflow


def test_release_workflow_always_publishes_sha_and_latest_digests() -> None:
    workflow = _read(RELEASE_WORKFLOW)

    assert ":latest" in workflow
    assert "sha-" in workflow
    assert "Resolve publish tags" in workflow


def test_release_workflow_uses_least_privilege_default_permissions() -> None:
    workflow = _read(RELEASE_WORKFLOW)
    # Workflow-level default is read; write is elevated only on jobs that need it.
    assert "permissions:\n  contents: read" in workflow
    assert "packages: write" in workflow
    assert "contents: write" in workflow


def test_project_version_is_semver_and_present() -> None:
    text = _read(PYPROJECT)
    assert 'version = "1.2.0"' in text
