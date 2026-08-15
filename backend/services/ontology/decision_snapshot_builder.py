"""Canonical adapter from recommendation output and durable evidence to a snapshot.

The recommendation action cannot consume its own durable EvidenceRecord because
runtime evidence is materialized only after action completion.  This adapter is
therefore the authoritative post-materialization boundary: owner input plus the
actual ActionResult plus tenant-scoped durable evidence become a DecisionSnapshot.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.domain.evidence import EvidenceRecord
from backend.services.ontology.commercial_state import goal_semantic_signature
from backend.services.ontology.decision_feedback import DecisionSnapshot
from backend.services.ontology.evidence_lineage import EvidenceLineage, EvidenceLineageResolution
from backend.services.tools.schemas import ActionResult, DecisionRecommendInput


def _algorithm_identity(output: dict[str, Any]) -> tuple[str, str]:
    raw = output.get("algorithm")
    if not isinstance(raw, dict):
        raise ValueError("recommendation output requires structured decision algorithm metadata")
    name = raw.get("name")
    version = raw.get("version")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("recommendation output algorithm name must be non-empty")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("recommendation output algorithm version must be non-empty")
    return name.strip(), version.strip()


def _record_lineage(record: EvidenceRecord) -> EvidenceLineage | None:
    raw = record.provenance_metadata.get("evidence_lineage")
    if raw is None:
        return None
    lineage = EvidenceLineage.model_validate(raw)
    if record.id is not None and lineage.artifact_evidence_id != str(record.id):
        raise ValueError("durable evidence lineage artifact identity must match EvidenceRecord.id")
    return lineage


def _relevant_lineages(
    *,
    evidence_records: list[EvidenceRecord],
    tenant_id: str,
    recommendation_output: dict[str, Any],
    supporting_ids: set[str],
    recommendation_input: DecisionRecommendInput,
) -> tuple[EvidenceLineage, ...]:
    """Select the result plus referenced supporting lineage; ignore unrelated records."""

    result_lineages: list[EvidenceLineage] = []
    supporting_lineages: list[EvidenceLineage] = []
    for record in evidence_records:
        if record.tenant_id != tenant_id:
            raise ValueError("decision snapshot evidence must belong to the decision tenant")
        lineage = _record_lineage(record)
        if lineage is None:
            continue
        role = record.provenance_metadata.get("evidence_role")
        source_evidence_id = record.provenance_metadata.get("source_evidence_id")
        composed_output = (
            record.structured_payload.get("decision_result") if isinstance(record.structured_payload, dict) else None
        )
        if role == "decision_recommendation_result" and (
            record.structured_payload == recommendation_output or composed_output == recommendation_output
        ):
            result_lineages.append(lineage)
        elif str(record.id) in supporting_ids or (
            isinstance(source_evidence_id, str) and source_evidence_id in supporting_ids
        ):
            supporting_lineages.append(lineage)

    if len(result_lineages) != 1:
        raise ValueError("decision snapshot requires exactly one matching durable recommendation result")
    result_artifact_id = result_lineages[0].artifact_evidence_id

    durable_artifact_ids = {item.artifact_evidence_id for item in supporting_lineages}
    input_lineages = [
        fact.lineage
        for fact in recommendation_input.evidence
        if (fact.evidence_id in supporting_ids or bool(set(fact.durable_source_evidence_ids) & supporting_ids))
        and fact.lineage is not None
        and fact.lineage.artifact_evidence_id not in durable_artifact_ids
    ]
    lineages = [*result_lineages, *supporting_lineages, *input_lineages]
    by_artifact: dict[str, EvidenceLineage] = {}
    for lineage in lineages:
        existing = by_artifact.get(lineage.artifact_evidence_id)
        if existing is not None and existing != lineage:
            raise ValueError("conflicting lineage contracts for one evidence artifact")
        by_artifact[lineage.artifact_evidence_id] = lineage
    result_lineage = by_artifact[result_artifact_id]
    if (
        result_lineage.resolution == EvidenceLineageResolution.PARTIAL
        and result_lineage.parent_evidence_ids
        and set(result_lineage.parent_evidence_ids) == supporting_ids
        and all(
            parent_id in by_artifact and by_artifact[parent_id].resolution == EvidenceLineageResolution.KNOWN
            for parent_id in result_lineage.parent_evidence_ids
        )
    ):
        parents = [by_artifact[parent_id] for parent_id in result_lineage.parent_evidence_ids]
        roots = tuple(sorted({root for parent in parents for root in parent.root_evidence_ids}))
        ancestors = tuple(
            sorted(
                {
                    identity
                    for parent in parents
                    for identity in (
                        parent.artifact_evidence_id,
                        *parent.parent_evidence_ids,
                        *parent.ancestor_evidence_ids,
                    )
                }
            )
        )
        source_identities = {parent.source_identity for parent in parents if parent.source_identity is not None}
        source_identity = next(iter(source_identities)) if len(source_identities) == 1 else None
        by_artifact[result_artifact_id] = EvidenceLineage(
            **result_lineage.model_dump(
                exclude={"source_identity", "root_evidence_ids", "ancestor_evidence_ids", "resolution"}
            ),
            source_identity=source_identity,
            root_evidence_ids=roots,
            ancestor_evidence_ids=ancestors,
            resolution=EvidenceLineageResolution.KNOWN,
        )
    return tuple(by_artifact[key] for key in sorted(by_artifact))


def build_decision_snapshot_from_recommendation(
    *,
    decision_id: str,
    tenant_id: str,
    recommendation_input: DecisionRecommendInput,
    recommendation_result: ActionResult,
    evidence_records: list[EvidenceRecord],
    decided_at: datetime,
) -> DecisionSnapshot:
    """Materialize owner semantics from the real recommendation/evidence path.

    No caller may supply semantic fields separately: intervention identity comes
    from the selected DecisionOption as serialized by the recommendation action,
    Goal/KPI meaning comes from the structured owner input, evidence lineage comes
    from durable tenant-owned records, and algorithm identity comes from the
    originating recommendation result.
    """

    if recommendation_result.action != "decision.recommend_next_action":
        raise ValueError("decision snapshot requires decision.recommend_next_action output")
    output = recommendation_result.output
    recommendation = output.get("recommendation")
    if not isinstance(recommendation, str) or not recommendation.strip():
        raise ValueError("recommendation output must contain a non-empty recommendation")
    intervention_key = output.get("intervention_key")
    if intervention_key is not None and not isinstance(intervention_key, str):
        raise ValueError("recommendation intervention_key must be a string or null")

    selected = next((option for option in recommendation_input.options if option.option_id == recommendation), None)
    expected_intervention = selected.intervention_key if selected is not None else None
    if intervention_key != expected_intervention:
        raise ValueError("recommendation intervention semantics disagree with the selected owner option")

    algorithm_name, algorithm_version = _algorithm_identity(output)
    goal_signature = (
        goal_semantic_signature(recommendation_input.goal_ref, recommendation_input.kpis)
        if recommendation_input.goal_ref is not None
        else None
    )
    supporting_ids = output.get("supporting_evidence_ids", [])
    option_scores = output.get("option_scores", [])
    uncertainty = output.get("uncertainty", [])
    if not isinstance(supporting_ids, list) or not all(isinstance(item, str) for item in supporting_ids):
        raise ValueError("supporting_evidence_ids must be a list of strings")
    if not isinstance(option_scores, list) or not all(isinstance(item, dict) for item in option_scores):
        raise ValueError("option_scores must be a list of objects")
    if not isinstance(uncertainty, list) or not all(isinstance(item, str) for item in uncertainty):
        raise ValueError("uncertainty must be a list of strings")

    return DecisionSnapshot(
        decision_id=decision_id,
        goal_id=recommendation_input.goal_ref.goal_id if recommendation_input.goal_ref else None,
        subject_refs=list(recommendation_input.subject_refs),
        recommendation=recommendation,
        intervention_key=expected_intervention,
        goal_semantic_signature=goal_signature,
        alternatives_considered=[
            option.option_id for option in recommendation_input.options if option.option_id != recommendation
        ],
        option_scores=option_scores,
        original_confidence=recommendation_result.confidence or 0.0,
        supporting_evidence_ids=supporting_ids,
        evidence_lineages=_relevant_lineages(
            evidence_records=evidence_records,
            tenant_id=tenant_id,
            recommendation_output=output,
            supporting_ids=set(supporting_ids),
            recommendation_input=recommendation_input,
        ),
        known_evidence_gaps=list(uncertainty),
        constraints=list(recommendation_input.constraints),
        uncertainty=list(uncertainty),
        algorithm_name=algorithm_name,
        algorithm_version=algorithm_version,
        decided_at=decided_at,
    )
