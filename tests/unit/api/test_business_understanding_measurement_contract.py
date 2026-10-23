from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from backend.api.routes.business_understanding import MeasurementCreate
from backend.services.business_understanding.service import (
    BusinessUnderstandingService,
    BusinessUnderstandingValidationError,
)
from backend.services.ontology.commercial_state import Goal, Kpi
from backend.services.ontology.types import BusinessObjectRef, BusinessObjectType


def _goal(*, subjects: list[BusinessObjectRef] | None = None) -> Goal:
    return Goal(
        goal_id="service-quality",
        objective_key="improve_service_quality",
        name="Improve service quality",
        subject_refs=subjects
        if subjects is not None
        else [
            BusinessObjectRef(object_type=BusinessObjectType.ORGANIZATION, object_id="tenant-business"),
            BusinessObjectRef(object_type=BusinessObjectType.ACCOUNT, object_id="service-line"),
        ],
    )


def _kpi() -> Kpi:
    return Kpi(
        kpi_id="defect-rate",
        goal_id="service-quality",
        name="Defect rate",
        metric="defect_rate",
        direction="decrease",
        current_value=0.12,
        target_value=0.05,
        unit="ratio",
    )


def _payload() -> dict[str, object]:
    goal = _goal()
    return {
        "goal": goal,
        "kpis": [_kpi()],
        "subject_references": [item.model_dump(mode="json") for item in goal.subject_refs],
        "source_kind": "customer_attested",
        "source_reference": {"source_id": "quality-report"},
        "source_version": "2026-01",
        "measurement_period_start": datetime(2026, 1, 1, tzinfo=UTC),
        "measurement_period_end": datetime(2026, 1, 31, tzinfo=UTC),
        "observed_at": datetime(2026, 2, 1, tzinfo=UTC),
    }


def test_measurement_contract_accepts_canonical_subjects_regardless_of_order() -> None:
    payload = _payload()
    payload["subject_references"] = list(reversed(payload["subject_references"]))  # type: ignore[arg-type]
    model = MeasurementCreate.model_validate(payload)
    assert len(model.subject_references) == 2


def test_measurement_contract_requires_exact_empty_subject_agreement() -> None:
    payload = _payload()
    payload["goal"] = _goal(subjects=[])
    with pytest.raises(ValidationError, match="measurement subjects must match goal subjects"):
        MeasurementCreate.model_validate(payload)


@pytest.mark.parametrize(
    "subjects",
    [
        [{"object_type": "organization", "object_id": "other"}],
        [{"object_type": "not-a-business-object", "object_id": "other"}],
        [{"object_type": "organization", "object_id": ""}],
    ],
)
def test_measurement_contract_rejects_mismatched_or_malformed_subjects(subjects: list[dict[str, str]]) -> None:
    payload = _payload()
    payload["subject_references"] = subjects
    with pytest.raises(ValidationError):
        MeasurementCreate.model_validate(payload)


def test_measurement_contract_rejects_naive_or_reversed_timing() -> None:
    naive = _payload()
    naive["observed_at"] = datetime(2026, 2, 1)
    with pytest.raises(ValidationError, match="observed_at must be timezone-aware"):
        MeasurementCreate.model_validate(naive)

    reversed_period = _payload()
    reversed_period["measurement_period_start"] = datetime(2026, 2, 1, tzinfo=UTC)
    reversed_period["measurement_period_end"] = datetime(2026, 1, 31, tzinfo=UTC)
    with pytest.raises(ValidationError, match="measurement period is invalid"):
        MeasurementCreate.model_validate(reversed_period)


def test_direct_service_rejects_unowned_verified_provenance_and_kpi_mismatch() -> None:
    goal = _goal()
    common = {
        "tenant_id": "tenant-a",
        "goal": goal,
        "kpis": [_kpi()],
        "subject_references": [item.model_dump(mode="json") for item in goal.subject_refs],
        "source_reference": {"source_id": "quality-report"},
        "source_version": "2026-01",
        "measurement_period_start": datetime(2026, 1, 1, tzinfo=UTC),
        "measurement_period_end": datetime(2026, 1, 31, tzinfo=UTC),
        "observed_at": datetime(2026, 2, 1, tzinfo=UTC),
        "limitations": [],
        "confidence": None,
        "producer": "unit-test",
    }
    service = BusinessUnderstandingService(Mock())
    with pytest.raises(BusinessUnderstandingValidationError, match="authorized internal adapter"):
        service.ingest_measurement(**common, source_kind="source_verified")

    wrong_kpi = _kpi().model_copy(update={"goal_id": "different-goal"})
    with pytest.raises(BusinessUnderstandingValidationError, match="belong to the supplied goal"):
        service.ingest_measurement(**{**common, "kpis": [wrong_kpi]}, source_kind="customer_attested")
