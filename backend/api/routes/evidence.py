from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.domain.evidence import EVIDENCE_CONTRACT_SCHEMA_VERSION, EvidenceRecord
from backend.repositories.capability_adapter_repository import CapabilityAdapterRepository
from backend.repositories.capability_repository import CapabilityRepository
from backend.repositories.evidence_repository import EvidenceRepository
from backend.repositories.execution_task_repository import ExecutionTaskRepository
from backend.repositories.mission_repository import MissionRepository

router = APIRouter(prefix="/evidence", tags=["evidence"])

EvidenceType = Literal[
    "observation",
    "artifact",
    "decision",
    "validation",
    "execution_trace",
    "operator_note",
    "external_reference",
]
EvidenceCollectionStatus = Literal[
    "draft", "collected", "verified", "rejected", "superseded", "retention_hold", "archived", "purged"
]


class EvidenceCreate(BaseModel):
    """Create a tenant-owned evidence contract record without runtime side effects."""

    model_config = ConfigDict(extra="forbid")

    mission_id: UUID
    task_graph_node_key: str | None = Field(default=None, min_length=1, max_length=160)
    materialization_reference: dict[str, Any] | None = None
    execution_task_id: UUID | None = None
    capability_id: UUID | None = None
    capability_adapter_id: UUID | None = None
    evidence_type: EvidenceType
    evidence_source: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=5000)
    structured_payload: dict[str, Any] = Field(default_factory=dict)
    artifact_references: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    provenance_metadata: dict[str, Any] = Field(default_factory=dict)
    trust_signal: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = Field(default=None, ge=0, le=1)
    collection_status: EvidenceCollectionStatus = "draft"

    @field_validator("task_graph_node_key", "evidence_source", "summary")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("text fields must be non-empty when provided")
        return value


class EvidenceUpdate(BaseModel):
    """Update mutable evidence metadata/status fields only."""

    model_config = ConfigDict(extra="forbid")

    collection_status: EvidenceCollectionStatus | None = None
    summary: str | None = Field(default=None, min_length=1, max_length=5000)
    structured_payload: dict[str, Any] | None = None
    artifact_references: list[dict[str, Any]] | None = Field(default=None, max_length=50)
    provenance_metadata: dict[str, Any] | None = None
    trust_signal: dict[str, Any] | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def _reject_explicit_null_patch_values(self) -> EvidenceUpdate:
        nullable_fields = {"confidence"}
        null_fields = [
            field for field in self.model_fields_set if field not in nullable_fields and getattr(self, field) is None
        ]
        if null_fields:
            joined_fields = ", ".join(sorted(null_fields))
            raise ValueError(f"evidence patch fields cannot be null: {joined_fields}")
        return self

    @field_validator("summary")
    @classmethod
    def _normalize_summary(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("summary must be non-empty when provided")
        return value


class EvidenceRead(BaseModel):
    """Evidence record response contract."""

    evidence_id: UUID
    tenant_id: str
    mission_id: UUID
    task_graph_node_key: str | None
    materialization_reference: dict[str, Any] | None
    execution_task_id: UUID | None
    capability_id: UUID | None
    capability_adapter_id: UUID | None
    evidence_type: str
    evidence_source: str
    summary: str
    structured_payload: dict[str, Any]
    artifact_references: list[dict[str, Any]]
    provenance_metadata: dict[str, Any]
    trust_signal: dict[str, Any]
    confidence: float | None
    collection_status: str
    schema_version: int
    created_at: str
    updated_at: str


class EvidenceListRead(BaseModel):
    """List response for evidence records."""

    evidence: list[EvidenceRead]


def _isoformat(value: datetime) -> str:
    return value.isoformat()


def _evidence_to_read(evidence: EvidenceRecord) -> EvidenceRead:
    return EvidenceRead(
        evidence_id=evidence.id,
        tenant_id=evidence.tenant_id,
        mission_id=evidence.mission_id,
        task_graph_node_key=evidence.task_graph_node_key,
        materialization_reference=evidence.materialization_reference,
        execution_task_id=evidence.execution_task_id,
        capability_id=evidence.capability_id,
        capability_adapter_id=evidence.capability_adapter_id,
        evidence_type=evidence.evidence_type,
        evidence_source=evidence.evidence_source,
        summary=evidence.summary,
        structured_payload=evidence.structured_payload,
        artifact_references=evidence.artifact_references,
        provenance_metadata=evidence.provenance_metadata,
        trust_signal=evidence.trust_signal,
        confidence=evidence.confidence,
        collection_status=evidence.collection_status,
        schema_version=evidence.schema_version,
        created_at=_isoformat(evidence.created_at),
        updated_at=_isoformat(evidence.updated_at),
    )


def _validate_references(*, body: EvidenceCreate, tenant_id: str, db: Session) -> None:
    mission = MissionRepository(db).get_for_tenant(mission_id=body.mission_id, tenant_id=tenant_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")

    capability = None
    if body.capability_id is not None:
        capability = CapabilityRepository(db).get_visible_for_tenant(
            capability_id=body.capability_id, tenant_id=tenant_id
        )
        if capability is None:
            raise HTTPException(status_code=422, detail="referenced capability is not visible to tenant")

    adapter = None
    if body.capability_adapter_id is not None:
        adapter = CapabilityAdapterRepository(db).get_visible_for_tenant(
            adapter_id=body.capability_adapter_id, tenant_id=tenant_id
        )
        if adapter is None:
            raise HTTPException(status_code=422, detail="referenced capability adapter is not visible to tenant")

    if capability is not None and adapter is not None:
        adapter_capability_id = getattr(adapter, "capability_id", None)
        if adapter_capability_id is not None:
            if adapter_capability_id != body.capability_id:
                raise HTTPException(status_code=422, detail="referenced capability adapter is not bound to capability")
        elif getattr(adapter, "capability_name", None) != getattr(capability, "name", None) or getattr(
            adapter, "capability_version", None
        ) != getattr(capability, "version", None):
            raise HTTPException(status_code=422, detail="referenced capability adapter is not bound to capability")

    if body.execution_task_id is not None:
        task = ExecutionTaskRepository(db).get(body.execution_task_id)
        if task is None or task.tenant_id != tenant_id or task.mission_id != body.mission_id:
            raise HTTPException(status_code=422, detail="referenced execution task is not owned by tenant mission")


@router.post("", response_model=EvidenceRead, status_code=status.HTTP_201_CREATED)
def create_evidence(
    body: EvidenceCreate,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> EvidenceRead:
    """Persist a proof/provenance evidence contract without runtime side effects."""
    tenant_scope = str(tenant_id)
    _validate_references(body=body, tenant_id=tenant_scope, db=db)

    evidence = EvidenceRepository(db).add(
        EvidenceRecord(
            tenant_id=tenant_scope,
            mission_id=body.mission_id,
            task_graph_node_key=body.task_graph_node_key,
            materialization_reference=body.materialization_reference,
            execution_task_id=body.execution_task_id,
            capability_id=body.capability_id,
            capability_adapter_id=body.capability_adapter_id,
            evidence_type=body.evidence_type,
            evidence_source=body.evidence_source,
            summary=body.summary,
            structured_payload=body.structured_payload,
            artifact_references=body.artifact_references,
            provenance_metadata=body.provenance_metadata,
            trust_signal=body.trust_signal,
            confidence=body.confidence,
            collection_status=body.collection_status,
            schema_version=EVIDENCE_CONTRACT_SCHEMA_VERSION,
        )
    )
    return _evidence_to_read(evidence)


@router.get("", response_model=EvidenceListRead)
def list_evidence(
    request: Request,
    mission_id: UUID = Query(...),
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> EvidenceListRead:
    """List tenant-owned evidence records for a tenant-owned mission."""
    tenant_scope = str(tenant_id)
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=tenant_scope)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")
    records = EvidenceRepository(db).list_for_mission(mission_id=mission_id, tenant_id=tenant_scope)
    return EvidenceListRead(evidence=[_evidence_to_read(record) for record in records])


@router.get("/{evidence_id}", response_model=EvidenceRead)
def read_evidence(
    evidence_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> EvidenceRead:
    """Read one tenant-owned evidence record."""
    evidence = EvidenceRepository(db).get_for_tenant(evidence_id=evidence_id, tenant_id=str(tenant_id))
    if evidence is None:
        raise HTTPException(status_code=404, detail="evidence not found for tenant")
    return _evidence_to_read(evidence)


@router.patch("/{evidence_id}", response_model=EvidenceRead)
def update_evidence(
    evidence_id: UUID,
    body: EvidenceUpdate,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> EvidenceRead:
    """Update mutable evidence status/metadata fields without runtime side effects."""
    repo = EvidenceRepository(db)
    evidence = repo.get_for_tenant(evidence_id=evidence_id, tenant_id=str(tenant_id))
    if evidence is None:
        raise HTTPException(status_code=404, detail="evidence not found for tenant")

    updates = body.model_dump(exclude_unset=True)
    for field_name, value in updates.items():
        setattr(evidence, field_name, value)

    return _evidence_to_read(repo.update(evidence))
