"""Static admission invocation contract; behavioral proof remains separate."""

from pathlib import Path

import pytest

from backend.services.runtime_admission_coverage import (
    INVOCATION_ANCHORS,
    RUNTIME_ADMISSION_COVERAGE,
    validate_runtime_admission_coverage,
)


def test_declared_controls_exist_inside_invocation_entry_points() -> None:
    assert len(INVOCATION_ANCHORS) == len(RUNTIME_ADMISSION_COVERAGE)
    validate_runtime_admission_coverage()


def test_control_token_outside_entry_function_does_not_satisfy_coverage(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    for boundary in RUNTIME_ADMISSION_COVERAGE:
        origin = root / boundary.source_path
        target = tmp_path / boundary.source_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(origin.read_text(encoding="utf-8"), encoding="utf-8")

    target = tmp_path / "backend/api/routes/mission.py"
    original = target.read_text(encoding="utf-8")
    entry_start = original.index("def admit_mission_graph_to_runtime(")
    invocation = original.index("graft_report = evaluate_admission_integrity(", entry_start)
    altered = (
        original[:invocation]
        + original[invocation:].replace(
            "graft_report = evaluate_admission_integrity(",
            "graft_report = fake_admission_check(",
            1,
        )
    )
    # The import still preserves the token elsewhere in the file, but the
    # entry function no longer invokes the required control.
    target.write_text(altered, encoding="utf-8")
    with pytest.raises(ValueError, match="invocation anchor missing"):
        validate_runtime_admission_coverage(repo_root=tmp_path)
