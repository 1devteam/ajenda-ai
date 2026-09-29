from pathlib import Path

import pytest

from backend.services.runtime_admission_coverage import (
    RUNTIME_ADMISSION_COVERAGE,
    validate_runtime_admission_coverage,
)


def test_runtime_admission_coverage_is_unique_and_fail_closed() -> None:
    validate_runtime_admission_coverage()

    ids = [boundary.boundary_id for boundary in RUNTIME_ADMISSION_COVERAGE]
    assert len(ids) == len(set(ids))
    assert all(boundary.fail_closed for boundary in RUNTIME_ADMISSION_COVERAGE)
    assert {"mission.graph_runtime_admission", "mission.runtime_queue_admission", "worker.dispatcher"} <= set(ids)


def test_runtime_admission_coverage_rejects_missing_source(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="source is missing"):
        validate_runtime_admission_coverage(repo_root=tmp_path)
