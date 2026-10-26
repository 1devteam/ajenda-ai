"""Contract and authority metadata tests for the governed measurement-write ability."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from backend.services.abilities.catalog import ABILITY_MANIFESTS_BY_ACTION
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.business_measurement_actions import IngestRuntimeMeasurementInput
from backend.services.tools.schemas import SideEffectClass


def test_measurement_write_registration_requires_explicit_governance() -> None:
    action = get_default_action_registry(rebuild=True).get("business.ingest_runtime_measurement")
    manifest = ABILITY_MANIFESTS_BY_ACTION[action.name]
    assert action.side_effect_class == SideEffectClass.INTERNAL_WRITE
    assert manifest.side_effect_class == SideEffectClass.INTERNAL_WRITE
    assert manifest.approval_required is True
    assert manifest.idempotency_required is True
    assert manifest.readback_required is True
    assert manifest.enabled_by_default is False
    assert manifest.provider == action.provider


def test_measurement_write_input_accepts_only_canonical_evidence_identity() -> None:
    evidence_id = uuid.uuid4()
    assert IngestRuntimeMeasurementInput(source_evidence_id=evidence_id).source_evidence_id == evidence_id
    with pytest.raises(ValidationError):
        IngestRuntimeMeasurementInput.model_validate(
            {"source_evidence_id": str(evidence_id), "kpis": [{"current_value": 99999}]}
        )
    with pytest.raises(ValidationError):
        IngestRuntimeMeasurementInput.model_validate({"source_evidence_id": "not-an-evidence-uuid"})
