"""Deterministic recurrence of observational business impacts.

Never derives intervention effectiveness, causation, Knowledge, or policy. A
non-overlapping lineage group is not a statistically independent source.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from backend.services.ontology.business_impact_observation import BusinessImpactObservation
from backend.services.ontology.commercial_state import KpiSemanticSignature
from backend.services.ontology.outcome import OutcomeStatus
from backend.services.ontology.types import BusinessObjectRef


class ObservedChangeDirection(StrEnum):
    FAVORABLE = "observed_favorable_change"
    REGRESSION = "observed_regression"
    NO_MATERIAL_CHANGE = "observed_no_material_change"
    INDETERMINATE = "observation_inconclusive"


class ObservationalRecurrenceStatus(StrEnum):
    CORRELATED_ONLY = "correlated_history_only"
    REPEATED_FAVORABLE = "repeated_favorable_observations"
    REPEATED_REGRESSION = "repeated_regression_observations"
    CONFLICTING = "conflicting_observations"
    INSUFFICIENT = "insufficient_directional_evidence"


class BusinessImpactPatternCandidate(BaseModel):
    """Inspect-only recurrence of selected-response and measured-outcome history."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    pattern_id: str
    selected_candidate_response_key: str
    objective_key: str
    subject_types: tuple[str, ...]
    kpi_semantic_signatures: tuple[KpiSemanticSignature, ...]
    status: ObservationalRecurrenceStatus
    episode_ids: tuple[str, ...]
    non_overlapping_lineage_groups: tuple[tuple[str, ...], ...]
    favorable_episode_ids: tuple[str, ...]
    regression_episode_ids: tuple[str, ...]
    neutral_episode_ids: tuple[str, ...]
    inconclusive_episode_ids: tuple[str, ...]
    customer_attested_episode_ids: tuple[str, ...]
    earliest_evaluated_at: str
    latest_evaluated_at: str
    limitations: tuple[str, ...] = (
        "observational_recurrence_not_intervention_recurrence",
        "selected_response_execution_not_established",
        "no_causal_attribution",
        "non_overlapping_lineage_not_independently_verified",
        "source_kind_is_not_independent_source_verification",
        "not_knowledge_not_policy_not_execution_authority",
    )
    is_knowledge: Literal[False] = False
    is_policy: Literal[False] = False


class BusinessImpactRecurrenceResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    pattern_candidates: tuple[BusinessImpactPatternCandidate, ...] = ()
    singleton_episode_ids: tuple[str, ...] = ()
    unclassified_episode_ids: tuple[str, ...] = ()
    explanation_codes: tuple[str, ...] = ()
    is_knowledge: Literal[False] = False
    is_policy: Literal[False] = False


def _identity(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "business-impact-pattern-v1:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _context(
    observation: BusinessImpactObservation,
) -> tuple[str, str, tuple[str, ...], tuple[KpiSemanticSignature, ...]] | None:
    provenance = observation.episode_reference.business_impact_provenance
    if not isinstance(provenance, dict):
        return None
    frozen = provenance.get("frozen_successor_contract")
    if not isinstance(frozen, dict):
        return None
    strategy = frozen.get("strategy_lineage")
    contract = frozen.get("measurement_contract")
    if not isinstance(strategy, dict) or not isinstance(contract, dict):
        return None
    response = strategy.get("selected_candidate_response_key")
    objective = contract.get("objective_key")
    metric = contract.get("metric")
    subjects = contract.get("subject_references")
    if (
        not isinstance(response, str)
        or not response
        or response != observation.selected_candidate_response_key
        or not isinstance(objective, str)
        or not objective
        or not isinstance(metric, str)
        or not metric
        or not isinstance(subjects, list)
        or not observation.subject_refs
        or not observation.kpi_semantic_signatures
    ):
        return None
    try:
        exact = {
            (ref.object_type.value, ref.object_id)
            for ref in (BusinessObjectRef.model_validate(item) for item in subjects)
        }
    except ValueError:
        return None
    observed_subjects = {(ref.object_type.value, ref.object_id) for ref in observation.subject_refs}
    if exact != observed_subjects:
        return None
    kpis = tuple(
        sorted(
            set(observation.kpi_semantic_signatures),
            key=lambda item: (item.metric, item.direction.value, item.normalized_unit or ""),
        )
    )
    if metric not in {item.metric for item in kpis}:
        return None
    return response, objective, tuple(sorted({item.object_type.value for item in observation.subject_refs})), kpis


def _direction(observation: BusinessImpactObservation) -> ObservedChangeDirection:
    """Observed goal status alone never establishes before/after movement.

    ACHIEVED may mean the baseline was already at target; PARTIAL_PROGRESS
    may hide mixed KPI directions. Never classify an incomplete or
    contradictory set of outcome deltas as favorable recurrence.
    """

    if not observation.kpi_deltas:
        return ObservedChangeDirection.INDETERMINATE
    gaps = [delta.gap_closed for delta in observation.kpi_deltas]
    if any(gap is None for gap in gaps):
        return ObservedChangeDirection.INDETERMINATE

    improved = any(gap is not None and gap > 0 for gap in gaps)
    regressed = any(gap is not None and gap < 0 for gap in gaps)
    if improved and regressed:
        return ObservedChangeDirection.INDETERMINATE
    if improved and observation.outcome_status in {OutcomeStatus.ACHIEVED, OutcomeStatus.PARTIAL_PROGRESS}:
        return ObservedChangeDirection.FAVORABLE
    if regressed and observation.outcome_status == OutcomeStatus.REGRESSED:
        return ObservedChangeDirection.REGRESSION
    if (
        not improved
        and not regressed
        and observation.outcome_status
        in {
            OutcomeStatus.ACHIEVED,
            OutcomeStatus.NO_MATERIAL_CHANGE,
        }
    ):
        return ObservedChangeDirection.NO_MATERIAL_CHANGE
    return ObservedChangeDirection.INDETERMINATE


def _lineage_tokens(observation: BusinessImpactObservation) -> frozenset[str]:
    provenance = observation.episode_reference.business_impact_provenance or {}
    frozen = provenance.get("frozen_successor_contract")
    mission_id = frozen.get("successor_mission_id") if isinstance(frozen, dict) else None
    tokens = {
        "baseline:" + str(observation.baseline_measurement_id),
        "observed:" + str(observation.observed_measurement_id),
        "evaluation:" + observation.outcome_evaluation_id,
        *("subject:" + ref.object_type.value + ":" + ref.object_id for ref in observation.subject_refs),
    }
    if isinstance(mission_id, str) and mission_id:
        tokens.add("successor_mission:" + mission_id)
    if isinstance(provenance.get("accepted_measurement_pairing_id"), str):
        tokens.add("pairing:" + provenance["accepted_measurement_pairing_id"])
    return frozenset(tokens)


def _groups(observations: list[BusinessImpactObservation]) -> tuple[tuple[str, ...], ...]:
    episodes = sorted(observations, key=lambda item: item.episode_reference.episode_id)
    parent = {item.episode_reference.episode_id: item.episode_reference.episode_id for item in episodes}

    def root(key: str) -> str:
        while parent[key] != key:
            key = parent[key]
        return key

    tokens: dict[str, str] = {}
    for observation in episodes:
        current = observation.episode_reference.episode_id
        for token in sorted(_lineage_tokens(observation)):
            previous = tokens.setdefault(token, current)
            left, right = root(current), root(previous)
            if left != right:
                parent[max(left, right)] = min(left, right)
    connected: dict[str, list[str]] = defaultdict(list)
    for episode in sorted(parent):
        connected[root(episode)].append(episode)
    return tuple(sorted((tuple(ids) for ids in connected.values()), key=lambda ids: ids[0]))


def evaluate_business_impact_recurrence(
    observations: list[BusinessImpactObservation],
) -> BusinessImpactRecurrenceResult:
    """Partition verified materializations by selected strategy and owner KPI context."""

    by_episode: dict[str, BusinessImpactObservation] = {}
    for observation in observations:
        episode_id = observation.episode_reference.episode_id
        if episode_id in by_episode and by_episode[episode_id] != observation:
            raise ValueError("business impact recurrence has a conflicting logical episode")
        by_episode[episode_id] = observation

    partitions: dict[
        tuple[str, str, tuple[str, ...], tuple[KpiSemanticSignature, ...]], list[BusinessImpactObservation]
    ] = defaultdict(list)
    unknown: list[str] = []
    for episode_id, observation in sorted(by_episode.items()):
        key = _context(observation)
        if key is None:
            unknown.append(episode_id)
        else:
            partitions[key].append(observation)

    candidates: list[BusinessImpactPatternCandidate] = []
    singletons: list[str] = []
    for key, entries in sorted(
        partitions.items(), key=lambda pair: (pair[0][0], pair[0][1], pair[0][2], str(pair[0][3]))
    ):
        if len(entries) == 1:
            singletons.append(entries[0].episode_reference.episode_id)
            continue
        groups = _groups(entries)
        favorable = tuple(
            sorted(
                item.episode_reference.episode_id
                for item in entries
                if _direction(item) == ObservedChangeDirection.FAVORABLE
            )
        )
        regression = tuple(
            sorted(
                item.episode_reference.episode_id
                for item in entries
                if _direction(item) == ObservedChangeDirection.REGRESSION
            )
        )
        neutral = tuple(
            sorted(
                item.episode_reference.episode_id
                for item in entries
                if _direction(item) == ObservedChangeDirection.NO_MATERIAL_CHANGE
            )
        )
        inconclusive = tuple(
            sorted(
                item.episode_reference.episode_id
                for item in entries
                if _direction(item) == ObservedChangeDirection.INDETERMINATE
            )
        )
        favorable_groups = sum(bool(set(group) & set(favorable)) for group in groups)
        regression_groups = sum(bool(set(group) & set(regression)) for group in groups)
        if len(groups) < 2:
            status = ObservationalRecurrenceStatus.CORRELATED_ONLY
        elif favorable and regression:
            status = ObservationalRecurrenceStatus.CONFLICTING
        elif favorable_groups >= 2:
            status = ObservationalRecurrenceStatus.REPEATED_FAVORABLE
        elif regression_groups >= 2:
            status = ObservationalRecurrenceStatus.REPEATED_REGRESSION
        else:
            status = ObservationalRecurrenceStatus.INSUFFICIENT
        times = sorted(item.evaluated_at.isoformat() for item in entries)
        response, objective, subject_types, kpis = key
        identity = _identity(
            {
                "response": response,
                "objective": objective,
                "subject_types": subject_types,
                "kpis": [item.model_dump(mode="json") for item in kpis],
            }
        )
        candidates.append(
            BusinessImpactPatternCandidate(
                pattern_id=identity,
                selected_candidate_response_key=response,
                objective_key=objective,
                subject_types=subject_types,
                kpi_semantic_signatures=kpis,
                status=status,
                episode_ids=tuple(sorted(item.episode_reference.episode_id for item in entries)),
                non_overlapping_lineage_groups=groups,
                favorable_episode_ids=favorable,
                regression_episode_ids=regression,
                neutral_episode_ids=neutral,
                inconclusive_episode_ids=inconclusive,
                customer_attested_episode_ids=tuple(
                    sorted(
                        item.episode_reference.episode_id
                        for item in entries
                        if item.baseline_source_kind == "customer_attested"
                        or item.observed_source_kind == "customer_attested"
                    )
                ),
                earliest_evaluated_at=times[0],
                latest_evaluated_at=times[-1],
            )
        )
    return BusinessImpactRecurrenceResult(
        pattern_candidates=tuple(sorted(candidates, key=lambda item: item.pattern_id)),
        singleton_episode_ids=tuple(sorted(singletons)),
        unclassified_episode_ids=tuple(sorted(unknown)),
        explanation_codes=("observational_only_no_intervention_qualification",),
    )
