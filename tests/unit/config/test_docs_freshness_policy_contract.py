"""Contract tests for Bundle 0.3 documentation freshness governance wiring."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PROJECT_SPEC = REPO_ROOT / "PROJECT_SPEC.md"
README = REPO_ROOT / "README.md"
DOCS_FRESHNESS_POLICY = REPO_ROOT / "docs" / "policies" / "DOCS_FRESHNESS_POLICY.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_project_spec_includes_docs_freshness_policy_in_canonical_list() -> None:
    """The canonical spec must list the docs freshness policy as governed source-of-truth context."""
    content = _read(PROJECT_SPEC)

    assert "`docs/policies/DOCS_FRESHNESS_POLICY.md`" in content


def test_readme_source_of_truth_docs_include_freshness_policy() -> None:
    """README source-of-truth inventory must include the freshness policy."""
    content = _read(README)

    assert "`docs/policies/DOCS_FRESHNESS_POLICY.md`" in content


def test_docs_freshness_policy_has_required_tier2_metadata_headers() -> None:
    """Tier-2 policy docs must carry status/owner/review metadata near the top."""
    content = _read(DOCS_FRESHNESS_POLICY)

    assert "**Status:** Active" in content
    assert "**Owner:**" in content
    assert "**Last reviewed:**" in content
