"""Observational recurrence never infers a selected strategy was executed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from backend.services.ontology.business_impact_observation import BusinessImpactObservation
from backend.services.ontology.business_impact_recurrence import (
    ObservationalRecurrenceStatus,
    evaluate_business_impact_recurrence,
)


def observation(
    *, index: int, subject_id: str | None = None, status: str = "achieved", selected_response: str = "inspect_funnel"
) -> BusinessImpactObservation:
    subject = {"object_type": "opportunity", "object_id": subject_id or f"opp-{index}"}
    baseline_id, observed_id = uuid4(), uuid4()
    observed_at = datetime(2026, 10, 21, tzinfo=UTC) + timedelta(days=index)
    episode_id = f"business-impact-{index}"
    evaluation_id = f"evaluation-{index}"
    return BusinessImpactObservation.model_validate(
        {
            "signal_id": f"impact-observation-{index}",
            "episode_reference": {
                "schema_version": 2,
                "episode_id": episode_id,
                "decision_id": None,
                "episode_kind": "business_impact",
                "outcome_evaluation_evidence_id": str(uuid4()),
                "business_impact_provenance": {
                    "baseline_measurement_id": str(baseline_id),
                    "observed_measurement_id": str(observed_id),
                    "outcome_evaluation_id": evaluation_id,
                    "accepted_measurement_pairing_id": str(uuid4()),
                    "frozen_successor_contract": {
                        "successor_mission_id": str(uuid4()),
                        "strategy_lineage": {
                            "selected_candidate_response_key": selected_response,
                        },
                        "measurement_contract": {
                            "objective_key": "increase_conversion",
                            "metric": "conversion",
                            "subject_references": [subject],
                        },
                    },
                },
            },
            "selected_candidate_response_key": selected_response,
            "baseline_measurement_id": str(baseline_id),
            "observed_measurement_id": str(observed_id),
            "baseline_source_kind": "customer_attested",
            "observed_source_kind": "customer_attested",
            "goal_id": "conversion-goal",
            "subject_refs": [subject],
            "kpi_semantic_signatures": [{"metric": "conversion", "direction": "increase"}],
            "kpi_deltas": [],
            "outcome_evaluation_id": evaluation_id,
            "outcome_status": status,
            "measured_outcome_attribution": "not_assessed",
            "outcome_timing_verification_basis": "source_supplied_under_contract",
            "observed_at": observed_at.isoformat(),
            "evaluated_at": (observed_at + timedelta(hours=1)).isoformat(),
        }
    )


def test_repeated_observation_uses_lineage_disjoint_groups_without_claiming_causation() -> None:
    first, second, third = observation(index=1), observation(index=2), observation(index=3, subject_id="opp-1")
    forward = evaluate_business_impact_recurrence([first, second, third])
    reverse = evaluate_business_impact_recurrence([third, second, first])
    assert forward == reverse
    candidate = forward.pattern_candidates[0]
    assert candidate.status == ObservationalRecurrenceStatus.REPEATED_FAVORABLE
    assert len(candidate.non_overlapping_lineage_groups) == 2
    assert sorted(map(len, candidate.non_overlapping_lineage_groups)) == [1, 2]
    assert len(candidate.customer_attested_episode_ids) == 3
    assert candidate.is_knowledge is False
    assert candidate.is_policy is False
    assert "no_causal_attribution" in candidate.limitations


def test_shared_subject_is_correlated_history_not_independent_evidence() -> None:
    result = evaluate_business_impact_recurrence(
        [observation(index=1), observation(index=2, subject_id="opp-1")]
    )
    assert result.pattern_candidates[0].status == ObservationalRecurrenceStatus.CORRELATED_ONLY
    assert len(result.pattern_candidates[0].non_overlapping_lineage_groups) == 1


def test_conflicting_observed_directions_do_not_become_support() -> None:
    result = evaluate_business_impact_recurrence(
        [observation(index=1), observation(index=2, status="regressed")]
    )
    candidate = result.pattern_candidates[0]
    assert candidate.status == ObservationalRecurrenceStatus.CONFLICTING
    assert candidate.favorable_episode_ids == ("business-impact-1",)
    assert candidate.regression_episode_ids == ("business-impact-2",)


def test_singleton_replay_and_contradiction_remain_fail_closed() -> None:
    first = observation(index=1)
    assert evaluate_business_impact_recurrence([first, first]).singleton_episode_ids == ("business-impact-1",)
    contradictory = first.model_copy(update={"outcome_status": "regressed"})
    with pytest.raises(ValueError, match="conflicting logical episode"):
        evaluate_business_impact_recurrence([first, contradictory])


def test_different_selected_response_and_objective_are_never_merged() -> None:
    first = observation(index=1)
    different_response = observation(index=2, selected_response="try_repricing")
    result = evaluate_business_impact_recurrence([first, different_response])
    assert result.pattern_candidates == ()
    assert result.singleton_episode_ids == ("business-impact-1", "business-impact-2")
