"""Deterministic current-state projection over immutable knowledge history."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy.orm import Session

from backend.domain.knowledge import KnowledgeArtifactRecord, KnowledgeQualificationRecord
from backend.repositories.knowledge_repository import KnowledgeRepository
from backend.services.knowledge.knowledge_ledger import KnowledgeLedgerIntegrityError
from backend.services.ontology.knowledge_qualification import (
    KnowledgeQualificationResult,
    KnowledgeQualificationStatus,
    QualifiedKnowledgeArtifact,
)

KNOWLEDGE_LIFECYCLE_ALGORITHM = "knowledge_lifecycle_resolution_v1"


class KnowledgeLifecycleStatus(StrEnum):
    ABSENT = "absent"
    PROVISIONAL = "provisional"
    ACTIVE = "active"
    CONTESTED = "contested"
    INVALIDATED = "invalidated"


class KnowledgeLifecycleHistoryItem(BaseModel):
    """Validated, immutable input independent of persistence implementation."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    qualification_record_id: uuid.UUID
    qualification: KnowledgeQualificationResult
    evaluation_watermark: datetime | None
    knowledge_record_id: uuid.UUID | None = None
    knowledge_artifact: QualifiedKnowledgeArtifact | None = None

    @model_validator(mode="after")
    def validate_ledger_shape(self) -> KnowledgeLifecycleHistoryItem:
        qualification = self.qualification
        artifact = self.knowledge_artifact
        if qualification.proposition is None:
            raise ValueError("lifecycle history requires proposition-bearing qualification")
        if self.evaluation_watermark != qualification.evidence_summary.latest_evaluated_at:
            raise ValueError("evaluation watermark disagrees with qualification payload")
        if qualification.status == KnowledgeQualificationStatus.QUALIFIED:
            if artifact is None or self.knowledge_record_id is None:
                raise ValueError("qualified lifecycle history requires a knowledge artifact")
            if qualification.qualified_knowledge != artifact:
                raise ValueError("knowledge artifact disagrees with qualification payload")
            if (
                artifact.proposition != qualification.proposition
                or artifact.qualification_id != qualification.qualification_id
                or artifact.source_candidate_id != qualification.source_candidate_id
                or artifact.algorithm != qualification.algorithm
            ):
                raise ValueError("knowledge artifact linkage disagrees with qualification")
        elif artifact is not None or self.knowledge_record_id is not None:
            raise ValueError("non-qualified lifecycle history must not have a knowledge artifact")
        return self


class CurrentKnowledgeState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    proposition_key: str
    lifecycle_status: KnowledgeLifecycleStatus
    evaluation_frontier: datetime | None
    authoritative_qualification_ids: tuple[str, ...]
    authoritative_knowledge_ids: tuple[str, ...]
    historical_qualification_count: int
    unordered_qualification_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    epistemic_limits: tuple[str, ...] = ()
    lifecycle_projection_id: str
    algorithm: str = KNOWLEDGE_LIFECYCLE_ALGORITHM
    is_policy: Literal[False] = False


_STATUS_MAP = {
    KnowledgeQualificationStatus.QUALIFIED: KnowledgeLifecycleStatus.ACTIVE,
    KnowledgeQualificationStatus.PROVISIONAL: KnowledgeLifecycleStatus.PROVISIONAL,
    KnowledgeQualificationStatus.INSUFFICIENT: KnowledgeLifecycleStatus.ABSENT,
    KnowledgeQualificationStatus.CONTESTED: KnowledgeLifecycleStatus.CONTESTED,
    KnowledgeQualificationStatus.INVALIDATED: KnowledgeLifecycleStatus.INVALIDATED,
}


def _projection_id(
    proposition_key: str,
    frontier: datetime | None,
    qualification_ids: tuple[str, ...],
    knowledge_ids: tuple[str, ...],
    status: KnowledgeLifecycleStatus,
) -> str:
    payload = {
        "algorithm": KNOWLEDGE_LIFECYCLE_ALGORITHM,
        "authoritative_knowledge_ids": knowledge_ids,
        "authoritative_qualification_ids": qualification_ids,
        "evaluation_frontier": frontier.isoformat() if frontier else None,
        "lifecycle_status": status.value,
        "proposition_key": proposition_key,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return f"knowledge-lifecycle-v1:{digest}"


def _resolve(
    history: Sequence[KnowledgeLifecycleHistoryItem], *, empty_proposition_key: str = ""
) -> CurrentKnowledgeState:
    items = tuple(KnowledgeLifecycleHistoryItem.model_validate(item) for item in history)
    if not items:
        status = KnowledgeLifecycleStatus.ABSENT
        return CurrentKnowledgeState(
            proposition_key=empty_proposition_key,
            lifecycle_status=status,
            evaluation_frontier=None,
            authoritative_qualification_ids=(),
            authoritative_knowledge_ids=(),
            historical_qualification_count=0,
            reason_codes=("no_qualification_history",),
            lifecycle_projection_id=_projection_id(empty_proposition_key, None, (), (), status),
        )

    proposition_keys = {
        item.qualification.proposition.proposition_key for item in items if item.qualification.proposition
    }
    if len(proposition_keys) != 1:
        raise ValueError("lifecycle history must contain exactly one proposition")
    proposition_key = next(iter(proposition_keys))

    # A repeated semantic identity is a replay only when its complete semantic input agrees.
    distinct: dict[str, KnowledgeLifecycleHistoryItem] = {}
    for item in items:
        identity = item.qualification.qualification_id
        previous = distinct.get(identity)
        if previous is not None and (
            previous.qualification != item.qualification
            or previous.evaluation_watermark != item.evaluation_watermark
            or previous.knowledge_artifact != item.knowledge_artifact
        ):
            raise ValueError("qualification identity has conflicting lifecycle history")
        distinct[identity] = item

    known = [item for item in distinct.values() if item.evaluation_watermark is not None]
    unordered = tuple(
        sorted(item.qualification.qualification_id for item in distinct.values() if item.evaluation_watermark is None)
    )
    reason_codes: set[str] = set()
    epistemic_limits: set[str] = set()
    if known:
        frontier_time = max(item.evaluation_watermark for item in known if item.evaluation_watermark is not None)
        frontier = [item for item in known if item.evaluation_watermark == frontier_time]
        if unordered:
            epistemic_limits.add("undated_history_not_authoritative")
    elif len(distinct) == 1:
        frontier_time = None
        frontier = list(distinct.values())
    else:
        frontier_time = None
        frontier = list(distinct.values())
        reason_codes.add("temporal_authority_unresolved")

    statuses = {item.qualification.status for item in frontier}
    if not known and len(distinct) > 1:
        lifecycle_status = KnowledgeLifecycleStatus.CONTESTED
    elif KnowledgeQualificationStatus.INVALIDATED in statuses:
        lifecycle_status = KnowledgeLifecycleStatus.INVALIDATED
    elif len(statuses) == 1:
        lifecycle_status = _STATUS_MAP[next(iter(statuses))]
    else:
        lifecycle_status = KnowledgeLifecycleStatus.CONTESTED

    qualification_ids = tuple(sorted(item.qualification.qualification_id for item in frontier))
    knowledge_ids = (
        tuple(sorted(item.knowledge_artifact.knowledge_id for item in frontier if item.knowledge_artifact))
        if lifecycle_status == KnowledgeLifecycleStatus.ACTIVE
        else ()
    )
    for item in frontier:
        reason_codes.update(item.qualification.reason_codes)
        epistemic_limits.update(item.qualification.epistemic_limits)
    return CurrentKnowledgeState(
        proposition_key=proposition_key,
        lifecycle_status=lifecycle_status,
        evaluation_frontier=frontier_time,
        authoritative_qualification_ids=qualification_ids,
        authoritative_knowledge_ids=knowledge_ids,
        historical_qualification_count=len(distinct),
        unordered_qualification_ids=unordered,
        reason_codes=tuple(sorted(reason_codes)),
        epistemic_limits=tuple(sorted(epistemic_limits)),
        lifecycle_projection_id=_projection_id(
            proposition_key, frontier_time, qualification_ids, knowledge_ids, lifecycle_status
        ),
    )


def resolve_knowledge_lifecycle(history: Sequence[KnowledgeLifecycleHistoryItem]) -> CurrentKnowledgeState:
    """Resolve one proposition's current state without I/O, clocks, or mutation."""

    return _resolve(history)


def _validate_record_payload(record: KnowledgeQualificationRecord) -> KnowledgeQualificationResult:
    try:
        qualification = KnowledgeQualificationResult.model_validate(record.qualification_payload)
    except Exception as exc:
        raise KnowledgeLedgerIntegrityError("stored qualification payload violates its owner contract") from exc
    if (
        qualification.proposition is None
        or record.qualification_id != qualification.qualification_id
        or record.proposition_key != qualification.proposition.proposition_key
        or record.qualification_status != qualification.status.value
        or record.source_candidate_id != qualification.source_candidate_id
        or record.evaluation_watermark != qualification.evidence_summary.latest_evaluated_at
        or record.algorithm != qualification.algorithm
    ):
        raise KnowledgeLedgerIntegrityError("qualification record columns disagree with owner payload")
    return qualification


def _validate_artifact_record(
    record: KnowledgeArtifactRecord, qualification_record: KnowledgeQualificationRecord
) -> QualifiedKnowledgeArtifact:
    try:
        artifact = QualifiedKnowledgeArtifact.model_validate(record.artifact_payload)
    except Exception as exc:
        raise KnowledgeLedgerIntegrityError("stored artifact payload violates its owner contract") from exc
    if (
        record.qualification_record_id != qualification_record.id
        or record.qualification_id != artifact.qualification_id
        or record.knowledge_id != artifact.knowledge_id
        or record.proposition_key != artifact.proposition.proposition_key
        or record.source_candidate_id != artifact.source_candidate_id
        or record.qualified_through_evaluated_at != artifact.qualified_through_evaluated_at
        or record.algorithm != artifact.algorithm
        or record.proposition_payload != artifact.proposition.model_dump(mode="json")
    ):
        raise KnowledgeLedgerIntegrityError("artifact record columns disagree with owner payload")
    return artifact


def resolve_current_knowledge_state(session: Session, *, tenant_id: str, proposition_key: str) -> CurrentKnowledgeState:
    """Load and validate tenant-owned history, then invoke the pure resolver."""

    repository = KnowledgeRepository(session)
    qualifications = repository.list_qualifications_for_proposition(
        tenant_id=tenant_id, proposition_key=proposition_key
    )
    artifacts = repository.list_artifacts_for_qualification_ids(
        tenant_id=tenant_id,
        qualification_ids=[record.qualification_id for record in qualifications],
    )
    artifacts_by_qualification: dict[str, KnowledgeArtifactRecord] = {}
    for artifact in artifacts:
        if artifact.qualification_id in artifacts_by_qualification:
            raise KnowledgeLedgerIntegrityError("qualification has multiple artifact records")
        artifacts_by_qualification[artifact.qualification_id] = artifact

    history: list[KnowledgeLifecycleHistoryItem] = []
    for record in qualifications:
        qualification = _validate_record_payload(record)
        artifact_record = artifacts_by_qualification.pop(record.qualification_id, None)
        validated_artifact = _validate_artifact_record(artifact_record, record) if artifact_record else None
        try:
            history.append(
                KnowledgeLifecycleHistoryItem(
                    qualification_record_id=record.id,
                    qualification=qualification,
                    evaluation_watermark=record.evaluation_watermark,
                    knowledge_record_id=artifact_record.id if artifact_record else None,
                    knowledge_artifact=validated_artifact,
                )
            )
        except ValueError as exc:
            raise KnowledgeLedgerIntegrityError("ledger structure violates lifecycle contract") from exc
    if artifacts_by_qualification:
        raise KnowledgeLedgerIntegrityError("artifact rows are not linked to selected qualification history")
    return _resolve(history, empty_proposition_key=proposition_key)
