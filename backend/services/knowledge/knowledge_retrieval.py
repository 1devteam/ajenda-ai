"""Deterministic retrieval of current, semantically relevant knowledge."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy.orm import Session

from backend.domain.knowledge import KnowledgeArtifactRecord
from backend.repositories.knowledge_repository import KnowledgeRepository
from backend.services.knowledge.knowledge_ledger import KnowledgeLedgerIntegrityError
from backend.services.knowledge.knowledge_lifecycle import (
    CurrentKnowledgeState,
    KnowledgeLifecycleStatus,
    resolve_current_knowledge_state,
)
from backend.services.ontology.commercial_state import (
    GoalSemanticComparison,
    GoalSemanticComparisonStatus,
    GoalSemanticSignature,
    compare_goal_semantics,
)
from backend.services.ontology.knowledge_qualification import (
    KnowledgeProposition,
    KnowledgeRelationshipType,
    QualifiedKnowledgeArtifact,
)
from backend.services.ontology.types import BusinessObjectSemanticSignature

KNOWLEDGE_RETRIEVAL_ALGORITHM = "knowledge_retrieval_v1"


class KnowledgeRetrievalQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    subject_semantic_signatures: tuple[BusinessObjectSemanticSignature, ...]
    goal_semantic_signature: GoalSemanticSignature
    intervention_keys: tuple[str, ...] = ()
    relationship_types: tuple[KnowledgeRelationshipType, ...] = (
        KnowledgeRelationshipType.ASSOCIATED_WITH_FAVORABLE_OUTCOME,
    )

    @model_validator(mode="after")
    def validate_semantic_bounds(self) -> KnowledgeRetrievalQuery:
        if not self.subject_semantic_signatures:
            raise ValueError("at least one subject semantic signature is required")
        if self.goal_semantic_signature.objective_key is None and not self.goal_semantic_signature.kpis:
            raise ValueError("objective key or KPI semantics are required")
        if not self.relationship_types:
            raise ValueError("at least one relationship type is required")
        return self


class RetrievedKnowledgeMatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    proposition: KnowledgeProposition
    current_state: CurrentKnowledgeState
    authoritative_artifacts: tuple[QualifiedKnowledgeArtifact, ...]
    goal_comparison: GoalSemanticComparison
    subject_match: Literal["exact_semantic_class_set"]
    intervention_match: Literal["exact", "unconstrained"]
    relationship_match: Literal["exact"]
    applicability_determined: Literal[False] = False
    reason_codes: tuple[str, ...] = ()
    epistemic_limits: tuple[str, ...] = ()
    is_policy: Literal[False] = False
    is_decision_instruction: Literal[False] = False


class KnowledgeRetrievalResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    query: KnowledgeRetrievalQuery
    matches: tuple[RetrievedKnowledgeMatch, ...]
    candidate_proposition_count: int
    active_proposition_count: int
    semantic_match_count: int
    retrieval_id: str
    reason_codes: tuple[str, ...] = ()
    epistemic_limits: tuple[str, ...] = ()
    algorithm: str = KNOWLEDGE_RETRIEVAL_ALGORITHM
    is_policy: Literal[False] = False
    is_decision_support: Literal[False] = False


def match_current_knowledge(
    *,
    query: KnowledgeRetrievalQuery,
    current_state: CurrentKnowledgeState,
    artifacts: Sequence[QualifiedKnowledgeArtifact],
) -> RetrievedKnowledgeMatch | None:
    """Apply owner semantics to an already lifecycle-resolved proposition."""

    if (
        current_state.lifecycle_status != KnowledgeLifecycleStatus.ACTIVE
        or not current_state.authoritative_knowledge_ids
    ):
        return None
    ordered = tuple(sorted(artifacts, key=lambda item: item.knowledge_id))
    expected = tuple(sorted(current_state.authoritative_knowledge_ids))
    if tuple(item.knowledge_id for item in ordered) != expected or len(set(expected)) != len(expected):
        raise KnowledgeLedgerIntegrityError("authoritative artifacts disagree with lifecycle authority")
    propositions = {item.proposition for item in ordered}
    if len(propositions) != 1:
        raise KnowledgeLedgerIntegrityError("authoritative artifacts disagree on proposition")
    proposition = next(iter(propositions))
    if proposition.proposition_key != current_state.proposition_key:
        raise KnowledgeLedgerIntegrityError("authoritative artifact proposition disagrees with lifecycle authority")
    if set(query.subject_semantic_signatures) != set(proposition.subject_semantic_signatures):
        return None
    if proposition.relationship_type not in query.relationship_types:
        return None
    intervention_match: Literal["exact", "unconstrained"] = "unconstrained"
    if query.intervention_keys:
        if proposition.intervention_key not in query.intervention_keys:
            return None
        intervention_match = "exact"
    goal = compare_goal_semantics(
        query.goal_semantic_signature,
        GoalSemanticSignature(objective_key=proposition.objective_key, kpis=proposition.kpi_semantic_signatures),
    )
    if goal.status not in {
        GoalSemanticComparisonStatus.EQUIVALENT,
        GoalSemanticComparisonStatus.PARTIALLY_EQUIVALENT,
    }:
        return None
    limits = set(current_state.epistemic_limits)
    if proposition.scope_conditions:
        limits.add("scope_conditions_not_evaluated")
    if proposition.invalidation_conditions:
        limits.add("invalidation_conditions_not_evaluated")
    if goal.status == GoalSemanticComparisonStatus.PARTIALLY_EQUIVALENT:
        limits.add("partial_goal_equivalence")
    return RetrievedKnowledgeMatch(
        proposition=proposition,
        current_state=current_state,
        authoritative_artifacts=ordered,
        goal_comparison=goal,
        subject_match="exact_semantic_class_set",
        intervention_match=intervention_match,
        relationship_match="exact",
        reason_codes=tuple(sorted(set(goal.reason_codes))),
        epistemic_limits=tuple(sorted(limits)),
    )


def _retrieval_id(query: KnowledgeRetrievalQuery, matches: Sequence[RetrievedKnowledgeMatch]) -> str:
    query_payload = query.model_dump(mode="json")
    query_payload["subject_semantic_signatures"] = sorted(
        query_payload["subject_semantic_signatures"], key=lambda item: json.dumps(item, sort_keys=True)
    )
    query_payload["intervention_keys"] = sorted(set(query_payload["intervention_keys"]))
    query_payload["relationship_types"] = sorted(set(query_payload["relationship_types"]))
    payload = {
        "algorithm": KNOWLEDGE_RETRIEVAL_ALGORITHM,
        "query": query_payload,
        "matches": [
            {
                "proposition_key": item.proposition.proposition_key,
                "lifecycle_projection_id": item.current_state.lifecycle_projection_id,
                "authoritative_knowledge_ids": sorted(item.current_state.authoritative_knowledge_ids),
            }
            for item in sorted(matches, key=lambda item: item.proposition.proposition_key)
        ],
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return f"knowledge-retrieval-v1:{digest}"


def _validate_artifact_record(record: KnowledgeArtifactRecord) -> QualifiedKnowledgeArtifact:
    try:
        artifact = QualifiedKnowledgeArtifact.model_validate(record.artifact_payload)
    except Exception as exc:
        raise KnowledgeLedgerIntegrityError("stored artifact payload violates its owner contract") from exc
    if (
        record.knowledge_id != artifact.knowledge_id
        or record.proposition_key != artifact.proposition.proposition_key
        or record.qualification_id != artifact.qualification_id
        or record.source_candidate_id != artifact.source_candidate_id
        or record.algorithm != artifact.algorithm
        or record.proposition_payload != artifact.proposition.model_dump(mode="json")
    ):
        raise KnowledgeLedgerIntegrityError("artifact record columns disagree with owner payload")
    return artifact


def retrieve_current_knowledge(
    session: Session, *, tenant_id: str, query: KnowledgeRetrievalQuery
) -> KnowledgeRetrievalResult:
    repository = KnowledgeRepository(session)
    keys = repository.list_candidate_proposition_keys_for_retrieval(
        tenant_id=tenant_id,
        subject_semantic_signatures=query.subject_semantic_signatures,
        goal_semantic_signature=query.goal_semantic_signature,
        intervention_keys=query.intervention_keys,
        relationship_types=query.relationship_types,
    )
    matches: list[RetrievedKnowledgeMatch] = []
    active_count = 0
    for key in sorted(set(keys)):
        state = resolve_current_knowledge_state(session, tenant_id=tenant_id, proposition_key=key)
        if state.lifecycle_status != KnowledgeLifecycleStatus.ACTIVE or not state.authoritative_knowledge_ids:
            continue
        active_count += 1
        records = repository.list_artifacts_for_knowledge_ids(
            tenant_id=tenant_id, knowledge_ids=state.authoritative_knowledge_ids
        )
        artifacts = [_validate_artifact_record(record) for record in records]
        match = match_current_knowledge(query=query, current_state=state, artifacts=artifacts)
        if match is not None:
            matches.append(match)
    ordered = tuple(sorted(matches, key=lambda item: item.proposition.proposition_key))
    limits = tuple(sorted({limit for item in ordered for limit in item.epistemic_limits}))
    reasons = () if ordered else ("no_current_semantic_knowledge_match",)
    return KnowledgeRetrievalResult(
        query=query,
        matches=ordered,
        candidate_proposition_count=len(set(keys)),
        active_proposition_count=active_count,
        semantic_match_count=len(ordered),
        retrieval_id=_retrieval_id(query, ordered),
        reason_codes=reasons,
        epistemic_limits=limits,
    )
