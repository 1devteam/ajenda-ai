"""Documentation drift guards for architecture decision records (ADRs)."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ADR_INDEX = REPO_ROOT / "docs" / "architecture" / "ADR_INDEX.md"
ADR_AUTHORITY = REPO_ROOT / "docs" / "architecture" / "ADR-0001-authority-classification-doctrine.md"
ADR_SCHEMA = REPO_ROOT / "docs" / "architecture" / "ADR-0002-schema-evolution-strategy.md"
ADR_READINESS = REPO_ROOT / "docs" / "architecture" / "ADR-0003-readiness-semantics-doctrine.md"


EXPECTED_ADR_LINKS = {
    "ADR-0001": "./ADR-0001-authority-classification-doctrine.md",
    "ADR-0002": "./ADR-0002-schema-evolution-strategy.md",
    "ADR-0003": "./ADR-0003-readiness-semantics-doctrine.md",
    "ADR-0007": "./ADR-0007-governed-vertical-role-catalog.md",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_adr_index_includes_bundle_0_2_seed_adrs() -> None:
    index_content = _read(ADR_INDEX)

    for adr_id, link in EXPECTED_ADR_LINKS.items():
        assert adr_id in index_content
        assert link in index_content


def test_seed_adrs_are_accepted_and_decision_structured() -> None:
    for adr_doc in (ADR_AUTHORITY, ADR_SCHEMA, ADR_READINESS):
        content = _read(adr_doc)

        assert "- **Status:** Accepted" in content
        assert "## Context" in content
        assert "## Decision" in content
        assert "## Consequences" in content
        assert "## Verification impact" in content
        assert "## Rollback strategy" in content
