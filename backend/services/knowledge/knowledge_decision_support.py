"""Bounded composition of applicable Knowledge into Decision-owned evidence.

Applicable knowledge may inform a decision only as bounded, provenance-preserving
evidence. Knowledge does not become policy, select an option, rewrite criteria or
weights, or acquire execution authority.

Knowledge-derived support is derived provenance. It is never an independent
world observation and cannot recursively strengthen its source proposition.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.services.knowledge.knowledge_applicability import (
    KnowledgeApplicabilityResolutionResult,
    KnowledgeApplicabilityStatus,
)
from backend.services.ontology.commercial_state import KpiSemanticSignature
from backend.services.ontology.evidence_lineage import (
    EvidenceLineage,
    EvidenceLineageResolution,
    EvidenceOriginType,
)
from backend.services.ontology.knowledge_qualification import (
    KnowledgeProposition,
    KnowledgeRelationshipType,
)
from backend.services.tools.schemas import (
    DecisionCriterion,
    DecisionOption,
    EvidenceFact,
    EvidenceFactStatus,
)

KNOWLEDGE_DECISION_SUPPORT_ALGORITHM = "knowledge_decision_support_v1"


class KnowledgeInfluenceDirection(StrEnum):
    SUPPORTS = "supports"
    OPPOSES = "opposes"
    CONDITIONAL = "conditional"
    NEUTRAL = "neutral"
    UNRESOLVED = "unresolved"


class KnowledgeDecisionInfluence(BaseModel):
    """What one applicable proposition says about one typed option/criterion."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    influence_id: str
    decision_id: str
    option_id: str
    criterion_id: str | None = None
    applicability_id: str
    proposition_key: str
    knowledge_ids: tuple[str, ...]
    direction: KnowledgeInfluenceDirection
    applicability_evidence_ids: tuple[str, ...] = ()
    supporting_episode_ids: tuple[str, ...] = ()
    qualification_ids: tuple[str, ...] = ()
    provenance_roots: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    epistemic_limits: tuple[str, ...] = ()
    evaluated_at: datetime
    algorithm: str = KNOWLEDGE_DECISION_SUPPORT_ALGORITHM
    provenance_class: Literal["derived_knowledge_influence"] = "derived_knowledge_influence"
    is_independent_observation: Literal[False] = False
    is_decision: Literal[False] = False
    is_policy: Literal[False] = False
    is_execution_instruction: Literal[False] = False


class KnowledgeDecisionSupportResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    support_id: str
    decision_id: str
    applicability: KnowledgeApplicabilityResolutionResult
    influences: tuple[KnowledgeDecisionInfluence, ...]
    knowledge_ids_considered: tuple[str, ...]
    applicability_evidence_ids: tuple[str, ...]
    supporting_episode_ids: tuple[str, ...]
    qualification_ids: tuple[str, ...]
    provenance_roots: tuple[str, ...]
    reason_codes: tuple[str, ...] = ()
    epistemic_limits: tuple[str, ...] = ()
    evaluated_at: datetime
    algorithm: str = KNOWLEDGE_DECISION_SUPPORT_ALGORITHM
    provenance_class: Literal["derived_knowledge_influence"] = "derived_knowledge_influence"
    is_independent_observation: Literal[False] = False
    is_decision: Literal[False] = False
    is_policy: Literal[False] = False
    is_execution_instruction: Literal[False] = False


class KnowledgeDecisionOption(DecisionOption):
    """Decision option with owner-produced canonical intervention identity."""


class KnowledgeDecisionCriterion(DecisionCriterion):
    """Decision criterion with an explicit owner-produced Knowledge alignment."""

    objective_key: str | None = Field(default=None, min_length=1, max_length=160)
    kpi_semantic_signature: KpiSemanticSignature | None = None

    @field_validator("objective_key")
    @classmethod
    def normalize_objective_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("objective_key must be a non-empty canonical identity")
        return normalized

    @model_validator(mode="after")
    def require_at_most_one_semantic_identity(self) -> KnowledgeDecisionCriterion:
        if self.objective_key is not None and self.kpi_semantic_signature is not None:
            raise ValueError("criterion must use one canonical semantic identity")
        return self


def _identity(prefix: str, payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return f"{prefix}:{hashlib.sha256(encoded).hexdigest()}"


def _criterion_matches(*, criterion: KnowledgeDecisionCriterion, proposition: KnowledgeProposition) -> bool:
    objective_key = proposition.objective_key
    kpis = proposition.kpi_semantic_signatures
    if criterion.objective_key is not None:
        return criterion.objective_key == objective_key
    if criterion.kpi_semantic_signature is not None:
        return criterion.kpi_semantic_signature in kpis
    return False


def evaluate_knowledge_decision_support(
    *,
    decision_id: str,
    options: tuple[KnowledgeDecisionOption, ...],
    criteria: tuple[KnowledgeDecisionCriterion, ...],
    applicability: KnowledgeApplicabilityResolutionResult,
    evaluated_at: datetime,
) -> KnowledgeDecisionSupportResult:
    """Translate canonical Applicability into non-numeric, bounded influences."""

    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("decision support evaluated_at must be timezone-aware")
    matches = {item.proposition.proposition_key: item for item in applicability.retrieval.matches}
    influences: list[KnowledgeDecisionInfluence] = []
    for evaluation in applicability.evaluations:
        if evaluation.evaluated_at > evaluated_at:
            raise ValueError("future applicability cannot inform an earlier decision support evaluation")
        match = matches.get(evaluation.proposition_key)
        if match is None:
            raise ValueError("applicability evaluation lacks its authoritative retrieval match")
        proposition = match.proposition
        qualification_ids = tuple(item.qualification_id for item in match.authoritative_qualifications)
        supporting_episode_ids = tuple(
            sorted(
                {
                    episode_id
                    for qualification in match.authoritative_qualifications
                    for episode_id in qualification.evidence_summary.supporting_episode_ids
                }
            )
        )
        roots = tuple(sorted({artifact.source_candidate_id for artifact in match.authoritative_artifacts}))
        base_limits = set(evaluation.epistemic_limits) | set(match.epistemic_limits)
        base_limits.add("derived_knowledge_not_independent_observation")
        if evaluation.status == KnowledgeApplicabilityStatus.PARTIALLY_APPLICABLE:
            base_limits.add("partial_applicability")
        for option in sorted(options, key=lambda item: item.option_id):
            if evaluation.status not in {
                KnowledgeApplicabilityStatus.APPLICABLE,
                KnowledgeApplicabilityStatus.PARTIALLY_APPLICABLE,
            }:
                direction = KnowledgeInfluenceDirection.UNRESOLVED
                criterion_matches: tuple[KnowledgeDecisionCriterion | None, ...] = (None,)
                reasons = {f"applicability_{evaluation.status.value}", "excluded_from_decision_evidence"}
            elif option.intervention_key is None:
                direction = KnowledgeInfluenceDirection.UNRESOLVED
                criterion_matches = (None,)
                reasons = {"option_intervention_semantics_missing"}
            elif option.intervention_key != proposition.intervention_key:
                direction = KnowledgeInfluenceDirection.NEUTRAL
                criterion_matches = (None,)
                reasons = {"canonical_intervention_identity_differs"}
            else:
                aligned = tuple(
                    item for item in criteria if _criterion_matches(criterion=item, proposition=proposition)
                )
                if not aligned:
                    direction = KnowledgeInfluenceDirection.UNRESOLVED
                    criterion_matches = (None,)
                    reasons = {"no_explicit_criterion_semantic_alignment"}
                elif proposition.relationship_type == KnowledgeRelationshipType.ASSOCIATED_WITH_FAVORABLE_OUTCOME:
                    direction = KnowledgeInfluenceDirection.SUPPORTS
                    criterion_matches = aligned
                    reasons = {"exact_intervention_and_criterion_alignment", "owner_favorable_relationship"}
                else:
                    direction = KnowledgeInfluenceDirection.UNRESOLVED
                    criterion_matches = aligned
                    reasons = {"knowledge_relationship_has_no_decision_direction_semantics"}
            for criterion in criterion_matches:
                payload = {
                    "decision_id": decision_id,
                    "option_id": option.option_id,
                    "criterion_id": criterion.criterion_id if criterion else None,
                    "applicability_id": evaluation.applicability_id,
                    "proposition_key": evaluation.proposition_key,
                    "knowledge_ids": sorted(evaluation.knowledge_ids),
                    "direction": direction.value,
                }
                influences.append(
                    KnowledgeDecisionInfluence(
                        influence_id=_identity("knowledge-influence-v1", payload),
                        decision_id=decision_id,
                        option_id=option.option_id,
                        criterion_id=criterion.criterion_id if criterion else None,
                        applicability_id=evaluation.applicability_id,
                        proposition_key=evaluation.proposition_key,
                        knowledge_ids=tuple(sorted(evaluation.knowledge_ids)),
                        direction=direction,
                        applicability_evidence_ids=evaluation.evidence_ids,
                        supporting_episode_ids=supporting_episode_ids,
                        qualification_ids=qualification_ids,
                        provenance_roots=roots,
                        reason_codes=tuple(sorted(reasons)),
                        epistemic_limits=tuple(sorted(base_limits)),
                        evaluated_at=evaluated_at,
                    )
                )
    ordered = tuple(sorted(influences, key=lambda item: item.influence_id))
    knowledge_ids = tuple(sorted({item for influence in ordered for item in influence.knowledge_ids}))
    applicability_evidence_ids = tuple(
        sorted({item for influence in ordered for item in influence.applicability_evidence_ids})
    )
    supporting_episode_ids = tuple(
        sorted(
            {
                item
                for influence in ordered
                if influence.direction == KnowledgeInfluenceDirection.SUPPORTS
                for item in influence.supporting_episode_ids
            }
        )
    )
    qualification_ids = tuple(sorted({item for influence in ordered for item in influence.qualification_ids}))
    roots = tuple(sorted({item for influence in ordered for item in influence.provenance_roots}))
    payload = {
        "decision_id": decision_id,
        "resolution_id": applicability.resolution_id,
        "influence_ids": [item.influence_id for item in ordered],
    }
    return KnowledgeDecisionSupportResult(
        support_id=_identity("knowledge-decision-support-v1", payload),
        decision_id=decision_id,
        applicability=applicability,
        influences=ordered,
        knowledge_ids_considered=knowledge_ids,
        applicability_evidence_ids=applicability_evidence_ids,
        supporting_episode_ids=supporting_episode_ids,
        qualification_ids=qualification_ids,
        provenance_roots=roots,
        reason_codes=tuple(sorted(set(applicability.reason_codes))),
        epistemic_limits=tuple(
            sorted({"derived_knowledge_not_independent_observation", *applicability.epistemic_limits})
        ),
        evaluated_at=evaluated_at,
    )


def knowledge_support_evidence_facts(
    support: KnowledgeDecisionSupportResult,
    *,
    episode_evidence_ids: dict[str, str],
) -> tuple[EvidenceFact, ...]:
    """Translate eligible support into bounded Decision facts with durable ancestry.

    Synthetic influence and Knowledge identities never masquerade as EvidenceRecord
    identities. Only SUPPORTS influences backed by resolved durable UUIDs become
    inferred facts; canonical Decision remains responsible for their numeric effect.
    """

    facts: list[EvidenceFact] = []
    for influence in support.influences:
        if influence.direction != KnowledgeInfluenceDirection.SUPPORTS or influence.criterion_id is None:
            continue
        if not influence.supporting_episode_ids:
            continue
        missing = sorted(set(influence.supporting_episode_ids) - episode_evidence_ids.keys())
        if missing:
            raise ValueError("Knowledge support episode lacks durable learning-signal evidence")
        durable_ids = tuple(sorted({episode_evidence_ids[item] for item in influence.supporting_episode_ids}))
        fact_id = _identity(
            "knowledge-decision-fact-v1",
            {
                "influence_id": influence.influence_id,
                "durable_source_evidence_ids": durable_ids,
            },
        )
        facts.append(
            EvidenceFact(
                evidence_id=fact_id,
                claim=(
                    f"Applicable Knowledge proposition {influence.proposition_key} supports "
                    f"option {influence.option_id} for criterion {influence.criterion_id}."
                ),
                status=EvidenceFactStatus.INFERRED,
                source="knowledge_decision_support_v1",
                # Qualified Knowledge adds no second numeric strength policy. Decision
                # owns the existing INFERRED multiplier; 1.0 means no extra attenuation.
                confidence=1.0,
                supports_option_ids=[influence.option_id],
                supports_criterion_ids=[influence.criterion_id],
                durable_source_evidence_ids=list(durable_ids),
                lineage=EvidenceLineage(
                    artifact_evidence_id=fact_id,
                    origin_type=EvidenceOriginType.DERIVED_FACT,
                    root_evidence_ids=durable_ids,
                    parent_evidence_ids=durable_ids,
                    ancestor_evidence_ids=durable_ids,
                    resolution=EvidenceLineageResolution.KNOWN,
                ),
            )
        )
    return tuple(sorted(facts, key=lambda item: item.evidence_id))
