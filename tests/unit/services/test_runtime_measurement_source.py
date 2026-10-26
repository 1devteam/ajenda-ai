"""Contract tests for the source-owned, runtime-read operating-measurement snapshot."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.services.business_understanding.measurement_source import RuntimeMeasurementSnapshot


def _snapshot() -> dict[str, object]:
    return {
        "goal": {
            "goal_id": "goal-a",
            "objective_key": "improve_conversion",
            "name": "Improve conversion",
            "subject_refs": [{"object_type": "opportunity", "object_id": "opp-a"}],
        },
        "kpis": [
            {
                "kpi_id": "conversion",
                "goal_id": "goal-a",
                "name": "Conversion",
                "metric": "conversion",
                "current_value": 0.5,
                "target_value": 1.0,
            }
        ],
        "source_version": "rev-1",
        "observed_at": datetime(2026, 2, 1, tzinfo=UTC),
        "measurement_period_start": datetime(2026, 1, 1, tzinfo=UTC),
        "measurement_period_end": datetime(2026, 1, 31, tzinfo=UTC),
    }


def test_source_snapshot_accepts_typed_single_source_measurement() -> None:
    snapshot = RuntimeMeasurementSnapshot.model_validate(_snapshot())
    assert snapshot.goal.goal_id == "goal-a"
    assert snapshot.kpis[0].current_value == 0.5


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"goal": {"goal_id": "goal-a", "name": "A", "subject_refs": []}}, "at least one business subject"),
        ({"kpis": []}, "at least 1 item"),
        ({"observed_at": datetime(2026, 2, 1)}, "timestamps must include timezone"),
        ({"measurement_period_end": datetime(2025, 12, 1, tzinfo=UTC)}, "period is reversed"),
        ({"observed_at": datetime(2026, 1, 15, tzinfo=UTC)}, "predates the end"),
    ],
)
def test_source_snapshot_fails_closed_on_invalid_fields(change: dict, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        RuntimeMeasurementSnapshot.model_validate({**_snapshot(), **change})


def test_source_snapshot_rejects_duplicate_kpi_identity_and_wrong_goal() -> None:
    values = _snapshot()
    single = values["kpis"][0]
    with pytest.raises(ValidationError, match="identities must be unique"):
        RuntimeMeasurementSnapshot.model_validate({**values, "kpis": [single, single]})
    with pytest.raises(ValidationError, match="does not belong"):
        RuntimeMeasurementSnapshot.model_validate(
            {**values, "kpis": [{**single, "goal_id": "unrelated"}]}
        )
