from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from backend.domain.knowledge import KnowledgeArtifactRecord, KnowledgeQualificationRecord
from backend.repositories.knowledge_repository import KnowledgeRepository
from backend.services.ontology.knowledge_qualification import (
    KnowledgeQualificationResult,
    KnowledgeQualificationStatus,
    QualifiedKnowledgeArtifact,
)


class KnowledgeLedgerIntegrityError(RuntimeError):
    """A semantic identity resolved to a different canonical owner payload."""


class KnowledgeLedgerWriteStatus(StrEnum):
    RECORDED = "recorded"
    ALREADY_RECORDED = "already_recorded"
    NOT_LEDGER_ELIGIBLE = "not_ledger_eligible"


class KnowledgeLedgerWriteResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    status: KnowledgeLedgerWriteStatus
    qualification_id: str
    proposition_key: str | None
    qualification_record_id: uuid.UUID | None
    knowledge_id: str | None = None
    artifact_record_id: uuid.UUID | None = None
    qualification_created: bool = False
    artifact_created: bool = False
    persistence_committed: bool
    is_policy: Literal[False] = False


def _canonical_result(payload: object) -> dict[str, object]:
    try:
        return KnowledgeQualificationResult.model_validate(payload).model_dump(mode="json")
    except Exception as exc:
        raise KnowledgeLedgerIntegrityError("stored qualification payload violates its owner contract") from exc


def _canonical_artifact(payload: object) -> dict[str, object]:
    try:
        return QualifiedKnowledgeArtifact.model_validate(payload).model_dump(mode="json")
    except Exception as exc:
        raise KnowledgeLedgerIntegrityError("stored artifact payload violates its owner contract") from exc


def _confirm_qualification(record: KnowledgeQualificationRecord, result: KnowledgeQualificationResult) -> None:
    if _canonical_result(record.qualification_payload) != result.model_dump(mode="json"):
        raise KnowledgeLedgerIntegrityError("qualification identity is bound to a different canonical payload")


def _confirm_artifact(record: KnowledgeArtifactRecord, artifact: QualifiedKnowledgeArtifact) -> None:
    if _canonical_artifact(record.artifact_payload) != artifact.model_dump(mode="json"):
        raise KnowledgeLedgerIntegrityError("knowledge identity is bound to a different canonical payload")


def record_knowledge_qualification(
    session: Session, *, tenant_id: str, result: KnowledgeQualificationResult
) -> KnowledgeLedgerWriteResult:
    """Append or confirm exact upstream knowledge records in the caller transaction."""

    validated = KnowledgeQualificationResult.model_validate(result.model_dump(mode="json"))
    if validated.proposition is None:
        return KnowledgeLedgerWriteResult(
            status=KnowledgeLedgerWriteStatus.NOT_LEDGER_ELIGIBLE,
            qualification_id=validated.qualification_id,
            proposition_key=None,
            qualification_record_id=None,
            persistence_committed=False,
        )
    artifact = validated.qualified_knowledge
    if (validated.status == KnowledgeQualificationStatus.QUALIFIED) != (artifact is not None):
        raise KnowledgeLedgerIntegrityError("qualification status and artifact eligibility disagree")
    if artifact is not None and (
        artifact.proposition != validated.proposition
        or artifact.qualification_id != validated.qualification_id
        or artifact.source_candidate_id != validated.source_candidate_id
        or artifact.algorithm != validated.algorithm
    ):
        raise KnowledgeLedgerIntegrityError("qualified artifact disagrees with its qualification result")

    repository = KnowledgeRepository(session)
    qualification_append = repository.append_qualification(
        tenant_id=tenant_id,
        qualification_id=validated.qualification_id,
        proposition_key=validated.proposition.proposition_key,
        qualification_status=validated.status.value,
        source_candidate_id=validated.source_candidate_id,
        evaluation_watermark=validated.evidence_summary.latest_evaluated_at,
        qualification_payload=validated.model_dump(mode="json"),
        algorithm=validated.algorithm,
    )
    qualification_record = qualification_append.record
    if not isinstance(qualification_record, KnowledgeQualificationRecord):
        raise KnowledgeLedgerIntegrityError("repository returned the wrong qualification record type")
    _confirm_qualification(qualification_record, validated)

    artifact_record: KnowledgeArtifactRecord | None = None
    artifact_created = False
    if artifact is not None:
        try:
            artifact_append = repository.append_artifact(
                tenant_id=tenant_id,
                qualification_record_id=qualification_record.id,
                knowledge_id=artifact.knowledge_id,
                proposition_key=validated.proposition.proposition_key,
                qualification_id=validated.qualification_id,
                source_candidate_id=validated.source_candidate_id,
                qualified_through_evaluated_at=artifact.qualified_through_evaluated_at,
                proposition_payload=validated.proposition.model_dump(mode="json"),
                artifact_payload=artifact.model_dump(mode="json"),
                algorithm=artifact.algorithm,
            )
        except RuntimeError as exc:
            raise KnowledgeLedgerIntegrityError(
                "artifact qualification identity is bound to another knowledge identity"
            ) from exc
        if not isinstance(artifact_append.record, KnowledgeArtifactRecord):
            raise KnowledgeLedgerIntegrityError("repository returned the wrong artifact record type")
        artifact_record = artifact_append.record
        artifact_created = artifact_append.created
        _confirm_artifact(artifact_record, artifact)
        if artifact_record.qualification_record_id != qualification_record.id:
            raise KnowledgeLedgerIntegrityError("knowledge identity is bound to another qualification record")

    created = qualification_append.created or artifact_created
    return KnowledgeLedgerWriteResult(
        status=KnowledgeLedgerWriteStatus.RECORDED if created else KnowledgeLedgerWriteStatus.ALREADY_RECORDED,
        qualification_id=validated.qualification_id,
        proposition_key=validated.proposition.proposition_key,
        qualification_record_id=qualification_record.id,
        knowledge_id=artifact.knowledge_id if artifact else None,
        artifact_record_id=artifact_record.id if artifact_record else None,
        qualification_created=qualification_append.created,
        artifact_created=artifact_created,
        persistence_committed=True,
    )
