"""Contract continuity at measurement ingress and canonical impact admission.

A frozen successor reference constrains the baseline and need identity. It
cannot itself produce a comparable outcome, causal claim, or learning signal.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from backend.services.business_understanding.service import (
    BusinessUnderstandingService,
    BusinessUnderstandingValidationError,
)


def _fixture():
    subject = {"schema_version": 1, "object_type": "organization", "object_id": "tenant-business"}
    baseline = SimpleNamespace(
        id=uuid4(),
        subject_references=[subject],
        objective_key="improve_service_quality",
        metric="defect_rate",
        source_content_fingerprint="sha256:" + "a" * 64,
        values=[{"kpi_id": "defect-rate", "metric": "defect_rate", "unit": "ratio"}],
        observed_at=datetime(2026, 1, 16, tzinfo=UTC),
        period_end=datetime(2026, 1, 15, tzinfo=UTC),
    )
    later = SimpleNamespace(
        id=uuid4(),
        subject_references=[subject],
        objective_key="improve_service_quality",
        metric="defect_rate",
        source_content_fingerprint="sha256:" + "d" * 64,
        values=list(baseline.values),
        observed_at=datetime(2026, 2, 16, tzinfo=UTC),
        period_start=datetime(2026, 2, 1, tzinfo=UTC),
        period_end=datetime(2026, 2, 15, tzinfo=UTC),
        intended_measurement_reference=None,
    )
    current = SimpleNamespace(
        id=uuid4(),
        need_id="need-a",
        revision=3,
        status="recognized",
        subject_references=[subject],
    )
    reference = {
        "schema_version": 1,
        "successor_mission_id": str(uuid4()),
        "successor_proposal_id": "proposal-a",
        "semantic_snapshot_id": "semantic:tenant-a:proposal-a",
        "semantic_snapshot_sha256": "sha256:" + "b" * 64,
        "strategy_lineage": {
            "need_id": "need-a",
            "need_revision": 2,
            "assessment_id": "assessment-a",
            "assessment_fingerprint": "sha256:" + "c" * 64,
            "selected_candidate_response_key": "inspect_funnel",
        },
        "measurement_contract": {
            "baseline_measurement_id": str(baseline.id),
            "baseline_source_content_fingerprint": baseline.source_content_fingerprint,
            "subject_references": [subject],
            "objective_key": "improve_service_quality",
            "metric": "defect_rate",
            "not_before": "2026-01-31T00:00:00+00:00",
        },
        "grants_execution_authority": False,
    }
    reference["contract_id"] = BusinessUnderstandingService.source_fingerprint(reference)
    later.intended_measurement_reference = reference
    return current, baseline, later


def _resign(reference: dict) -> None:
    reference["contract_id"] = BusinessUnderstandingService.source_fingerprint(
        {key: value for key, value in reference.items() if key != "contract_id"}
    )


def _accepted_pairing(*, current, baseline, later):
    return SimpleNamespace(
        id=uuid4(),
        need_id=current.need_id,
        need_revision=current.revision,
        need_revision_id=current.id,
        baseline_measurement_id=baseline.id,
        observed_measurement_id=later.id,
        successor_contract_id=later.intended_measurement_reference["contract_id"],
        status="accepted",
        outcome_evidence_id=None,
        outcome_evaluation_id=None,
        impact_revision_id=None,
    )


def test_valid_successor_reference_does_not_replace_outcome_evidence() -> None:
    current, baseline, later = _fixture()
    BusinessUnderstandingService._validate_measurement_comparability(current=current, baseline=baseline, later=later)
    BusinessUnderstandingService._validate_successor_measurement_impact_lineage(
        current=current, baseline=baseline, later=later
    )

    service = BusinessUnderstandingService(MagicMock())
    service._repository = MagicMock()
    service._repository.get_need_revision_for_tenant.return_value = current
    service._repository.get_latest_need_for_tenant.return_value = current
    service._repository.get_measurement_for_tenant.side_effect = [baseline, later]
    pairing = _accepted_pairing(current=current, baseline=baseline, later=later)
    service._repository.lock_measurement_pairing_for_tenant.return_value = pairing
    with patch("backend.services.business_understanding.service.EvidenceRepository") as evidence_repository:
        evidence_repository.return_value.get_for_tenant.return_value = None
        with pytest.raises(BusinessUnderstandingValidationError, match="canonical outcome evidence"):
            service.record_canonical_measurement_impact(
                tenant_id="tenant-a",
                need_id=current.need_id,
                expected_revision=current.revision,
                baseline_measurement_id=baseline.id,
                observed_measurement_id=later.id,
                outcome_evidence_id=uuid4(),
                accepted_measurement_pairing_id=pairing.id,
                producer="unit-test",
            )
        evidence_repository.return_value.get_for_tenant.assert_called_once()
    service._repository.append_need_revision.assert_not_called()



def test_impact_rejects_action_label_without_canonical_runtime_evidence() -> None:
    """A caller-authored EvidenceRecord must not earn outcome authority."""
    from backend.services.tools.evidence_bridge import CanonicalToolEvidenceError

    current, baseline, later = _fixture()
    service = BusinessUnderstandingService(MagicMock())
    service._repository = MagicMock()
    service._repository.get_need_revision_for_tenant.return_value = current
    service._repository.get_latest_need_for_tenant.return_value = current
    service._repository.get_measurement_for_tenant.side_effect = [baseline, later]
    pairing = _accepted_pairing(current=current, baseline=baseline, later=later)
    service._repository.lock_measurement_pairing_for_tenant.return_value = pairing
    evidence_id = uuid4()
    alleged_outcome = SimpleNamespace(
        id=evidence_id,
        mission_id=uuid4(),
        provenance_metadata={"action_name": "analysis.evaluate_outcome"},
        structured_payload={},
    )
    with (
        patch("backend.services.business_understanding.service.EvidenceRepository") as evidence_repository,
        patch(
            "backend.services.business_understanding.service.require_canonical_tool_action_evidence",
            side_effect=CanonicalToolEvidenceError("no completed runtime lineage"),
        ) as canonical_proof,
    ):
        evidence_repository.return_value.get_for_tenant.return_value = alleged_outcome
        with pytest.raises(BusinessUnderstandingValidationError, match="authorized runtime provenance"):
            service.record_canonical_measurement_impact(
                tenant_id="tenant-a",
                need_id=current.need_id,
                expected_revision=current.revision,
                baseline_measurement_id=baseline.id,
                observed_measurement_id=later.id,
                outcome_evidence_id=evidence_id,
                accepted_measurement_pairing_id=pairing.id,
                producer="unit-test",
            )
        canonical_proof.assert_called_once_with(
            session=service._session,
            record=alleged_outcome,
            expected_action="analysis.evaluate_outcome",
            expected_role=None,
        )
    service._repository.append_need_revision.assert_not_called()


@pytest.mark.parametrize(
    "field, value",
    [
        ("wrong_baseline_id", "00000000-0000-4000-8000-000000000001"),
        ("wrong_baseline_fingerprint", "sha256:" + "e" * 64),
        ("wrong_need", "need-unrelated"),
        ("future_need_revision", 999),
        ("wrong_metric", "response_time"),
        ("wrong_objective", "unrelated_goal"),
        ("old_period_start", datetime(2026, 1, 25, tzinfo=UTC)),
        ("old_period_end_without_start", datetime(2026, 1, 25, tzinfo=UTC)),
        ("invalid_authority", True),
        ("malformed_subjects", [{"object_type": "alien", "object_id": "unknown"}]),
    ],
)
def test_contradictory_successor_reference_rejected_before_outcome_access(field: str, value) -> None:
    current, baseline, later = _fixture()
    reference = deepcopy(later.intended_measurement_reference)
    strategy = reference["strategy_lineage"]
    contract = reference["measurement_contract"]
    if field == "wrong_baseline_id":
        contract["baseline_measurement_id"] = value
    elif field == "wrong_baseline_fingerprint":
        contract["baseline_source_content_fingerprint"] = value
    elif field == "wrong_need":
        strategy["need_id"] = value
    elif field == "future_need_revision":
        strategy["need_revision"] = value
    elif field == "wrong_metric":
        contract["metric"] = value
    elif field == "wrong_objective":
        contract["objective_key"] = value
    elif field == "old_period_start":
        later.period_start = value
    elif field == "old_period_end_without_start":
        later.period_start = None
        later.period_end = value
    elif field == "invalid_authority":
        reference["grants_execution_authority"] = value
    elif field == "malformed_subjects":
        contract["subject_references"] = value
    _resign(reference)
    later.intended_measurement_reference = reference

    service = BusinessUnderstandingService(MagicMock())
    service._repository = MagicMock()
    service._repository.get_need_revision_for_tenant.return_value = current
    service._repository.get_latest_need_for_tenant.return_value = current
    service._repository.get_measurement_for_tenant.side_effect = [baseline, later]
    pairing = _accepted_pairing(current=current, baseline=baseline, later=later)
    service._repository.lock_measurement_pairing_for_tenant.return_value = pairing
    with patch("backend.services.business_understanding.service.EvidenceRepository") as evidence_repository:
        with pytest.raises(BusinessUnderstandingValidationError):
            service.record_canonical_measurement_impact(
                tenant_id="tenant-a",
                need_id=current.need_id,
                expected_revision=current.revision,
                baseline_measurement_id=baseline.id,
                observed_measurement_id=later.id,
                outcome_evidence_id=uuid4(),
                accepted_measurement_pairing_id=pairing.id,
                producer="unit-test",
            )
        evidence_repository.assert_not_called()
    service._repository.append_need_revision.assert_not_called()


def test_invalid_contract_id_is_rejected() -> None:
    current, baseline, later = _fixture()
    later.intended_measurement_reference["contract_id"] = "sha256:" + "f" * 64
    with pytest.raises(BusinessUnderstandingValidationError, match="identity"):
        BusinessUnderstandingService._validate_successor_measurement_impact_lineage(
            current=current, baseline=baseline, later=later
        )


def test_legacy_measurement_without_successor_claim_retains_existing_impact_rules() -> None:
    current, baseline, later = _fixture()
    later.intended_measurement_reference = None
    BusinessUnderstandingService._validate_measurement_comparability(current=current, baseline=baseline, later=later)
    BusinessUnderstandingService._validate_successor_measurement_impact_lineage(
        current=current, baseline=baseline, later=later
    )


def test_accept_measurement_pairing_is_idempotent_and_has_no_outcome_effect() -> None:
    current, baseline, later = _fixture()
    current.id = uuid4()
    service = BusinessUnderstandingService(MagicMock())
    service._repository = MagicMock()
    service._repository.get_measurement_for_tenant.side_effect = [baseline, later, baseline, later]
    service._repository.get_measurement_pairing_by_fingerprint_for_tenant.side_effect = [None]
    service._repository.get_need_revision_for_tenant.return_value = current
    service._repository.add_measurement_pairing.side_effect = lambda pairing: pairing

    with patch("backend.services.business_understanding.service.EvidenceRepository") as evidence_repository:
        pairing = service.accept_measurement_pairing(
            tenant_id="tenant-a",
            need_id=current.need_id,
            expected_revision=current.revision,
            baseline_measurement_id=baseline.id,
            observed_measurement_id=later.id,
            producer="unit-test",
        )
        service._repository.get_measurement_pairing_by_fingerprint_for_tenant.side_effect = [pairing]
        retry = service.accept_measurement_pairing(
            tenant_id="tenant-a",
            need_id=current.need_id,
            expected_revision=current.revision,
            baseline_measurement_id=baseline.id,
            observed_measurement_id=later.id,
            producer="unit-test",
        )

    assert pairing.status == "accepted"
    assert pairing.outcome_evidence_id is None
    assert pairing.outcome_evaluation_id is None
    assert pairing.impact_revision_id is None
    assert pairing.need_revision_id == current.id
    assert retry is pairing
    service._repository.add_measurement_pairing.assert_called_once()
    evidence_repository.assert_not_called()
    service._repository.append_need_revision.assert_not_called()


def test_superseded_need_rejects_successor_reference_before_outcome_access() -> None:
    current, baseline, later = _fixture()
    current.status = "superseded"
    service = BusinessUnderstandingService(MagicMock())
    service._repository = MagicMock()
    service._repository.get_need_revision_for_tenant.return_value = current
    service._repository.get_latest_need_for_tenant.return_value = current
    service._repository.get_measurement_for_tenant.side_effect = [baseline, later]
    pairing = _accepted_pairing(current=current, baseline=baseline, later=later)
    service._repository.lock_measurement_pairing_for_tenant.return_value = pairing

    with patch("backend.services.business_understanding.service.EvidenceRepository") as evidence_repository:
        with pytest.raises(BusinessUnderstandingValidationError, match="superseded need"):
            service.record_canonical_measurement_impact(
                tenant_id="tenant-a",
                need_id=current.need_id,
                expected_revision=current.revision,
                baseline_measurement_id=baseline.id,
                observed_measurement_id=later.id,
                outcome_evidence_id=uuid4(),
                accepted_measurement_pairing_id=pairing.id,
                producer="unit-test",
            )
        evidence_repository.assert_not_called()
    service._repository.append_need_revision.assert_not_called()


def test_successor_resolver_rejects_backdated_measurement_period() -> None:
    service = BusinessUnderstandingService(MagicMock())
    mission_id = uuid4()
    current, baseline, later = _fixture()
    reference = later.intended_measurement_reference
    snap = {
        "snapshot_id": reference["semantic_snapshot_id"],
        "content_sha256": reference["semantic_snapshot_sha256"],
        "business_need_reference": {
            "need_id": current.need_id,
            "revision": 2,
        },
        "business_need_assessment_reference": {
            "assessment_id": "assessment-a",
            "assessment_fingerprint": reference["strategy_lineage"]["assessment_fingerprint"],
            "response_advancement": {
                "selected_candidate_response_key": "inspect_funnel",
                "baseline_measurement": {
                    "measurement_id": str(baseline.id),
                    "source_content_fingerprint": baseline.source_content_fingerprint,
                },
                "intended_measurement": {
                    **reference["measurement_contract"],
                    "baseline_measurement_id": str(baseline.id),
                },
            },
        },
    }
    mission = SimpleNamespace(
        id=mission_id,
        metadata_json={
            "mission_intake": {
                "context": {
                    "composition": {
                        "reviewed_proposal_id": "proposal-a",
                        "semantic_snapshot": snap,
                    }
                }
            }
        },
    )
    with patch("backend.services.business_understanding.service.MissionRepository") as missions:
        missions.return_value.get_reference_for_tenant.return_value = mission
        subject = current.subject_references
        with pytest.raises(BusinessUnderstandingValidationError, match="period must follow"):
            service._resolve_intended_measurement_reference(
                tenant_id="tenant-a",
                successor_mission_id=mission_id,
                subject_references=subject,
                objective_key="improve_service_quality",
                metric="defect_rate",
                observed_at=datetime(2026, 2, 16, tzinfo=UTC),
                measurement_period_start=datetime(2026, 1, 25, tzinfo=UTC),
            )
        with pytest.raises(BusinessUnderstandingValidationError, match="period must follow"):
            service._resolve_intended_measurement_reference(
                tenant_id="tenant-a",
                successor_mission_id=mission_id,
                subject_references=subject,
                objective_key="improve_service_quality",
                metric="defect_rate",
                observed_at=datetime(2026, 2, 16, tzinfo=UTC),
                measurement_period_end=datetime(2026, 1, 25, tzinfo=UTC),
            )
        resolved = service._resolve_intended_measurement_reference(
            tenant_id="tenant-a",
            successor_mission_id=mission_id,
            subject_references=subject,
            objective_key="improve_service_quality",
            metric="defect_rate",
            observed_at=datetime(2026, 2, 16, tzinfo=UTC),
            measurement_period_start=datetime(2026, 2, 1, tzinfo=UTC),
        )
        assert resolved is not None
        assert resolved["measurement_contract"]["baseline_measurement_id"] == str(baseline.id)


@pytest.mark.parametrize("defect", ["foreign_need", "wrong_baseline", "wrong_later"])
def test_impact_rejects_pairing_identity_mismatch_before_evidence_access(defect: str) -> None:
    current, baseline, later = _fixture()
    pairing = SimpleNamespace(
        id=uuid4(),
        need_id=current.need_id,
        baseline_measurement_id=baseline.id,
        observed_measurement_id=later.id,
        status="accepted",
    )
    if defect == "foreign_need":
        pairing.need_id = "another-need"
    elif defect == "wrong_baseline":
        pairing.baseline_measurement_id = uuid4()
    else:
        pairing.observed_measurement_id = uuid4()

    service = BusinessUnderstandingService(MagicMock())
    service._repository = MagicMock()
    service._repository.lock_measurement_pairing_for_tenant.return_value = pairing
    with patch("backend.services.business_understanding.service.EvidenceRepository") as evidence_repository:
        with pytest.raises(BusinessUnderstandingValidationError, match="contradicts"):
            service.record_canonical_measurement_impact(
                tenant_id="tenant-a",
                need_id=current.need_id,
                expected_revision=current.revision,
                baseline_measurement_id=baseline.id,
                observed_measurement_id=later.id,
                outcome_evidence_id=uuid4(),
                accepted_measurement_pairing_id=pairing.id,
                producer="unit-test",
            )
        evidence_repository.assert_not_called()
    service._repository.append_need_revision.assert_not_called()


def test_impact_rejects_accepted_pairing_from_different_need_revision() -> None:
    current, baseline, later = _fixture()
    current.id = uuid4()
    pairing = SimpleNamespace(
        id=uuid4(),
        need_id=current.need_id,
        baseline_measurement_id=baseline.id,
        observed_measurement_id=later.id,
        need_revision_id=uuid4(),
        need_revision=current.revision,
        status="accepted",
    )
    service = BusinessUnderstandingService(MagicMock())
    service._repository = MagicMock()
    service._repository.lock_measurement_pairing_for_tenant.return_value = pairing
    service._repository.get_need_revision_for_tenant.return_value = current
    with patch("backend.services.business_understanding.service.EvidenceRepository") as evidence_repository:
        with pytest.raises(BusinessUnderstandingValidationError, match="requested need revision"):
            service.record_canonical_measurement_impact(
                tenant_id="tenant-a",
                need_id=current.need_id,
                expected_revision=current.revision,
                baseline_measurement_id=baseline.id,
                observed_measurement_id=later.id,
                outcome_evidence_id=uuid4(),
                accepted_measurement_pairing_id=pairing.id,
                producer="unit-test",
            )
        evidence_repository.assert_not_called()
    service._repository.append_need_revision.assert_not_called()
