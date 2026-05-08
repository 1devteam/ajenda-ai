"""Documentation contract tests for validation artifact provenance."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ARTIFACT_README = REPO_ROOT / "artifacts" / "validation" / "README.md"
MATRIX_DOC = REPO_ROOT / "docs" / "validation" / "live-runtime-matrix.md"
VALIDATION_LIB = REPO_ROOT / "scripts" / "validation" / "lib.sh"

EXPECTED_SCENARIO_RESULTS_COLUMNS = [
    "scenario_id",
    "run_outcome",
    "evidence_status",
    "evidence_basis",
    "validation_env",
    "artifact_path",
    "notes",
]
EXPECTED_EVIDENCE_BASIS_VALUES = ["runner_backed", "integration_backed", "unsupported"]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _artifact_readme() -> str:
    return _read(ARTIFACT_README)


def _extract_documented_column_order(content: str) -> list[str]:
    match = re.search(r"Column order: `([^`]+)`", content)
    assert match is not None, "artifact README must document scenario_results.tsv column order"
    return [column.strip() for column in match.group(1).split(",")]


def _extract_runner_tsv_header(content: str) -> list[str]:
    match = re.search(r"printf '([^']+)' > \"\$RESULTS_TSV\"", content)
    assert match is not None, "validation lib must write scenario_results.tsv header"
    header = match.group(1).removesuffix(r"\n")
    return header.split(r"\t")


def _extract_allowed_evidence_basis_values(content: str) -> list[str]:
    match = re.search(
        r"Allowed `evidence_basis` values are exactly:\n\n(?P<bullets>(?:- `[^`]+` .+\n)+)",
        content,
    )
    assert match is not None, "artifact README must document exact evidence_basis values"
    return re.findall(r"^- `([^`]+)`", match.group("bullets"), flags=re.MULTILINE)


def test_artifact_readme_documents_evidence_basis_file() -> None:
    """The artifact README must document the per-scenario evidence_basis file."""
    content = _artifact_readme()

    assert "`evidence_basis.txt`" in content


def test_artifact_readme_documents_scenario_results_column_order_exactly() -> None:
    """The artifact README must document the scenario ledger column order exactly."""
    assert _extract_documented_column_order(_artifact_readme()) == EXPECTED_SCENARIO_RESULTS_COLUMNS


def test_artifact_readme_documents_summary_evidence_basis_counts_path() -> None:
    """The artifact README must document the summary.json evidence-basis count path."""
    content = _artifact_readme()

    assert "`summary.json.evidence_basis_counts`" in content


def test_artifact_readme_documents_allowed_evidence_basis_values_exactly() -> None:
    """The artifact README must document only the supported evidence_basis values."""
    assert _extract_allowed_evidence_basis_values(_artifact_readme()) == EXPECTED_EVIDENCE_BASIS_VALUES


def test_artifact_readme_does_not_list_not_executed_as_evidence_basis() -> None:
    """not_executed is a run outcome and must not appear in the evidence_basis value list."""
    allowed_values = _extract_allowed_evidence_basis_values(_artifact_readme())

    assert "not_executed" not in allowed_values


def test_artifact_readme_documents_blocked_precondition_failures_as_unsupported() -> None:
    """Blocked rows caused by failed preconditions must be documented as unsupported evidence."""
    content = _artifact_readme()

    assert "required preconditions fail" in content
    assert "`run_outcome=blocked`" in content
    assert "`evidence_basis=unsupported`" in content


def test_artifact_readme_and_runner_agree_on_scenario_results_tsv_header() -> None:
    """The documented scenario_results.tsv column order must match the runner header."""
    documented_columns = _extract_documented_column_order(_artifact_readme())
    runner_columns = _extract_runner_tsv_header(_read(VALIDATION_LIB))

    assert documented_columns == runner_columns


def test_matrix_documents_evidence_basis_as_dynamic_artifact_provenance() -> None:
    """The matrix must separate dynamic provenance from static validation backing."""
    content = _read(MATRIX_DOC)

    assert "### Artifact provenance boundary" in content
    assert "`evidence_basis` is dynamic artifact provenance" in content
    assert "`validation_backing` is static matrix metadata" in content
    assert "`unsupported` provenance must not satisfy release-gating evidence requirements" in content


def test_artifact_readme_keeps_evidence_basis_values_aligned_with_matrix() -> None:
    """Artifact provenance docs must use the same evidence-basis vocabulary as the matrix."""
    artifact_values = _extract_allowed_evidence_basis_values(_artifact_readme())
    matrix_content = _read(MATRIX_DOC)

    for value in artifact_values:
        assert f"`{value}`" in matrix_content
