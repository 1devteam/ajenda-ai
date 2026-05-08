"""Documentation contract tests for validation artifact provenance."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ARTIFACT_README = REPO_ROOT / "artifacts" / "validation" / "README.md"
MATRIX_DOC = REPO_ROOT / "docs" / "validation" / "live-runtime-matrix.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_artifact_readme_documents_evidence_basis_provenance_surfaces() -> None:
    """The artifact README must describe every runner-emitted provenance surface."""
    content = _read(ARTIFACT_README)

    assert "## Artifact provenance" in content
    assert "`evidence_basis.txt`" in content
    assert "evidence basis" in content
    assert "fourth column of `scenario_results.tsv`" in content
    assert "`evidence_basis_counts`" in content


def test_matrix_documents_evidence_basis_as_dynamic_artifact_provenance() -> None:
    """The matrix must separate dynamic provenance from static validation backing."""
    content = _read(MATRIX_DOC)

    assert "### Artifact provenance boundary" in content
    assert "`evidence_basis` is dynamic artifact provenance" in content
    assert "`validation_backing` is static matrix metadata" in content
    assert "`unsupported` provenance must not satisfy release-gating evidence requirements" in content


def test_artifact_readme_keeps_evidence_basis_values_aligned_with_matrix() -> None:
    """Artifact provenance docs must use the same evidence-basis vocabulary as the matrix."""
    artifact_content = _read(ARTIFACT_README)
    matrix_content = _read(MATRIX_DOC)

    for value in ("runner_backed", "integration_backed", "unsupported"):
        assert f"`{value}`" in artifact_content
        assert f"`{value}`" in matrix_content
