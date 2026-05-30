from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from backend.api.routes._authorization import require_route_permission
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.auth.permissions import Permission
from backend.domain.retrieval_contract import (
    RETRIEVAL_CONTRACT_SCHEMA_VERSION,
    RETRIEVAL_STATUSES,
    RETRIEVAL_STRATEGIES,
    RetrievalContract,
)
from backend.repositories.mission_repository import MissionRepository
from backend.repositories.retrieval_contract_repository import RetrievalContractRepository

router = APIRouter(prefix="/retrieval-contracts", tags=["retrieval-contracts"])

RetrievalStatus = Literal["requested", "fulfilled", "rejected", "superseded", "revoked"]
RetrievalStrategy = Literal["semantic", "keyword", "hybrid", "operator_selected", "policy_selected", "procedural"]

assert set(RETRIEVAL_STATUSES) == {"requested", "fulfilled", "rejected", "superseded", "revoked"}
assert set(RETRIEVAL_STRATEGIES) == {
    "semantic",
    "keyword",
    "hybrid",
    "operator_selected",
    "policy_selected",
    "procedural",
}


def _validate_memory_reference_shape(field_name: str, references: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for index, reference in enumerate(references):
        memory_id = reference.get("memory_id")
        if memory_id is None:
            raise ValueError(f"{field_name}[{index}] must include memory_id")
        try:
            UUID(str(memory_id))
        except ValueError as exc:
            raise ValueError(f"{field_name}[{index}].memory_id must be a UUID") from exc
    return references


def _validate_memory_references_for_mission(
    *, references: list[dict[str, Any]], field_name: str, mission_id: UUID, tenant_id: str
) -> None:
    for reference in references:
        reference_tenant_id = reference.get("tenant_id")
        if reference_tenant_id is not None and str(reference_tenant_id) != tenant_id:
            raise HTTPException(status_code=422, detail=f"{field_name} are not owned by tenant mission")
        reference_mission_id = reference.get("mission_id")
        if reference_mission_id is not None:
            try:
                parsed_mission_id = UUID(str(reference_mission_id))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=f"{field_name}.mission_id must be a UUID") from exc
            if parsed_mission_id != mission_id:
                raise HTTPException(status_code=422, detail=f"{field_name} are not owned by tenant mission")


class RetrievalContractCreate(BaseModel):
    """Create a tenant-owned retrieval and recall contract without runtime side effects."""

    model_config = ConfigDict(extra="forbid")

    mission_id: UUID
    retrieval_request: dict[str, Any] = Field(default_factory=dict)
    retrieval_reason: str = Field(min_length=1, max_length=5000)
    retrieval_strategy: RetrievalStrategy
    strategy_metadata: dict[str, Any] = Field(default_factory=dict)
    retrieval_filters: dict[str, Any] = Field(default_factory=dict)
    governance_constraints: dict[str, Any] = Field(default_factory=dict)
    memory_references: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    returned_memory_references: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    confidence: float | None = Field(default=None, ge=0, le=1)
    trust_signal: dict[str, Any] = Field(default_factory=dict)
    provenance_metadata: dict[str, Any] = Field(default_factory=dict)
    retrieval_status: RetrievalStatus = "requested"
    superseded_by_retrieval_id: UUID | None = None
    revocation_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("retrieval_reason")
    @classmethod
    def _normalize_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text fields must be non-empty")
        return value

    @field_validator("memory_references")
    @classmethod
    def _validate_memory_references(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return _validate_memory_reference_shape("memory_references", value)

    @field_validator("returned_memory_references")
    @classmethod
    def _validate_returned_memory_references(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return _validate_memory_reference_shape("returned_memory_references", value)


class RetrievalContractUpdate(BaseModel):
    """Update mutable retrieval contract status and metadata fields only."""

    model_config = ConfigDict(extra="forbid")

    retrieval_request: dict[str, Any] | None = None
    retrieval_reason: str | None = Field(default=None, min_length=1, max_length=5000)
    retrieval_strategy: RetrievalStrategy | None = None
    strategy_metadata: dict[str, Any] | None = None
    retrieval_filters: dict[str, Any] | None = None
    governance_constraints: dict[str, Any] | None = None
    memory_references: list[dict[str, Any]] | None = Field(default=None, max_length=100)
    returned_memory_references: list[dict[str, Any]] | None = Field(default=None, max_length=100)
    confidence: float | None = Field(default=None, ge=0, le=1)
    trust_signal: dict[str, Any] | None = None
    provenance_metadata: dict[str, Any] | None = None
    retrieval_status: RetrievalStatus | None = None
    superseded_by_retrieval_id: UUID | None = None
    revocation_metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _reject_explicit_null_patch_values(self) -> RetrievalContractUpdate:
        nullable_fields = {"confidence", "superseded_by_retrieval_id"}
        null_fields = [
            field for field in self.model_fields_set if field not in nullable_fields and getattr(self, field) is None
        ]
        if null_fields:
            joined_fields = ", ".join(sorted(null_fields))
            raise ValueError(f"retrieval contract patch fields cannot be null: {joined_fields}")
        return self

    @field_validator("retrieval_reason")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("text fields must be non-empty when provided")
        return value

    @field_validator("memory_references")
    @classmethod
    def _validate_memory_references(cls, value: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        if value is None:
            return None
        return _validate_memory_reference_shape("memory_references", value)

    @field_validator("returned_memory_references")
    @classmethod
    def _validate_returned_memory_references(cls, value: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        if value is None:
            return None
        return _validate_memory_reference_shape("returned_memory_references", value)


class RetrievalContractRead(BaseModel):
    """Retrieval and recall contract response contract."""

    retrieval_id: UUID
    tenant_id: str
    mission_id: UUID
    retrieval_request: dict[str, Any]
    retrieval_reason: str
    retrieval_strategy: str
    strategy_metadata: dict[str, Any]
    retrieval_filters: dict[str, Any]
    governance_constraints: dict[str, Any]
    memory_references: list[dict[str, Any]]
    returned_memory_references: list[dict[str, Any]]
    confidence: float | None
    trust_signal: dict[str, Any]
    provenance_metadata: dict[str, Any]
    retrieval_status: str
    superseded_by_retrieval_id: UUID | None
    revocation_metadata: dict[str, Any]
    schema_version: int
    created_at: str
    updated_at: str


class RetrievalContractListRead(BaseModel):
    """List response for retrieval and recall contracts."""

    retrieval_contracts: list[RetrievalContractRead]


def _isoformat(value: datetime) -> str:
    return value.isoformat()


def _retrieval_to_read(retrieval: RetrievalContract) -> RetrievalContractRead:
    return RetrievalContractRead(
        retrieval_id=retrieval.id,
        tenant_id=retrieval.tenant_id,
        mission_id=retrieval.mission_id,
        retrieval_request=retrieval.retrieval_request,
        retrieval_reason=retrieval.retrieval_reason,
        retrieval_strategy=retrieval.retrieval_strategy,
        strategy_metadata=retrieval.strategy_metadata,
        retrieval_filters=retrieval.retrieval_filters,
        governance_constraints=retrieval.governance_constraints,
        memory_references=retrieval.memory_references,
        returned_memory_references=retrieval.returned_memory_references,
        confidence=retrieval.confidence,
        trust_signal=retrieval.trust_signal,
        provenance_metadata=retrieval.provenance_metadata,
        retrieval_status=retrieval.retrieval_status,
        superseded_by_retrieval_id=retrieval.superseded_by_retrieval_id,
        revocation_metadata=retrieval.revocation_metadata,
        schema_version=retrieval.schema_version,
        created_at=_isoformat(retrieval.created_at),
        updated_at=_isoformat(retrieval.updated_at),
    )


def _validate_mission(*, mission_id: UUID, tenant_id: str, db: Session) -> None:
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=tenant_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")


@router.post("", response_model=RetrievalContractRead, status_code=status.HTTP_201_CREATED)
def create_retrieval_contract(
    body: RetrievalContractCreate,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> RetrievalContractRead:
    """Persist a retrieval and recall contract without runtime side effects."""
    require_route_permission(request=request, db=db, permission=Permission.RETRIEVAL_MANAGE, tenant_id=tenant_id)
    tenant_scope = str(tenant_id)
    _validate_mission(mission_id=body.mission_id, tenant_id=tenant_scope, db=db)
    _validate_memory_references_for_mission(
        references=body.memory_references,
        field_name="memory_references",
        mission_id=body.mission_id,
        tenant_id=tenant_scope,
    )
    _validate_memory_references_for_mission(
        references=body.returned_memory_references,
        field_name="returned_memory_references",
        mission_id=body.mission_id,
        tenant_id=tenant_scope,
    )

    retrieval = RetrievalContractRepository(db).add(
        RetrievalContract(
            tenant_id=tenant_scope,
            mission_id=body.mission_id,
            retrieval_request=body.retrieval_request,
            retrieval_reason=body.retrieval_reason,
            retrieval_strategy=body.retrieval_strategy,
            strategy_metadata=body.strategy_metadata,
            retrieval_filters=body.retrieval_filters,
            governance_constraints=body.governance_constraints,
            memory_references=body.memory_references,
            returned_memory_references=body.returned_memory_references,
            confidence=body.confidence,
            trust_signal=body.trust_signal,
            provenance_metadata=body.provenance_metadata,
            retrieval_status=body.retrieval_status,
            superseded_by_retrieval_id=body.superseded_by_retrieval_id,
            revocation_metadata=body.revocation_metadata,
            schema_version=RETRIEVAL_CONTRACT_SCHEMA_VERSION,
        )
    )
    return _retrieval_to_read(retrieval)


@router.get("", response_model=RetrievalContractListRead)
def list_retrieval_contracts(
    mission_id: UUID = Query(...),
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> RetrievalContractListRead:
    """List tenant-owned retrieval contracts for a tenant-owned mission."""
    tenant_scope = str(tenant_id)
    _validate_mission(mission_id=mission_id, tenant_id=tenant_scope, db=db)
    records = RetrievalContractRepository(db).list_for_mission(mission_id=mission_id, tenant_id=tenant_scope)
    return RetrievalContractListRead(retrieval_contracts=[_retrieval_to_read(record) for record in records])


@router.get("/{retrieval_id}", response_model=RetrievalContractRead)
def read_retrieval_contract(
    retrieval_id: UUID,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> RetrievalContractRead:
    """Read one tenant-owned retrieval contract."""
    retrieval = RetrievalContractRepository(db).get_for_tenant(retrieval_id=retrieval_id, tenant_id=str(tenant_id))
    if retrieval is None:
        raise HTTPException(status_code=404, detail="retrieval contract not found for tenant")
    return _retrieval_to_read(retrieval)


@router.patch("/{retrieval_id}", response_model=RetrievalContractRead)
def update_retrieval_contract(
    retrieval_id: UUID,
    body: RetrievalContractUpdate,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> RetrievalContractRead:
    """Update mutable retrieval contract status/metadata fields without runtime side effects."""
    require_route_permission(request=request, db=db, permission=Permission.RETRIEVAL_MANAGE, tenant_id=tenant_id)
    tenant_scope = str(tenant_id)
    repo = RetrievalContractRepository(db)
    retrieval = repo.get_for_tenant(retrieval_id=retrieval_id, tenant_id=tenant_scope)
    if retrieval is None:
        raise HTTPException(status_code=404, detail="retrieval contract not found for tenant")

    updates = body.model_dump(exclude_unset=True)
    if "memory_references" in updates:
        _validate_memory_references_for_mission(
            references=updates["memory_references"],
            field_name="memory_references",
            mission_id=retrieval.mission_id,
            tenant_id=tenant_scope,
        )
    if "returned_memory_references" in updates:
        _validate_memory_references_for_mission(
            references=updates["returned_memory_references"],
            field_name="returned_memory_references",
            mission_id=retrieval.mission_id,
            tenant_id=tenant_scope,
        )

    for field_name, value in updates.items():
        setattr(retrieval, field_name, value)

    return _retrieval_to_read(repo.update(retrieval))
