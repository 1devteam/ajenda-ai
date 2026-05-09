from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.domain.capability import CAPABILITY_REGISTRY_SCHEMA_VERSION, Capability
from backend.repositories.capability_repository import CapabilityRepository

router = APIRouter(prefix="/capabilities", tags=["capabilities"])

CapabilityRiskLevel = Literal["low", "medium", "high", "critical"]
CapabilityScope = Literal["tenant", "global"]


class CapabilityApprovalRequirements(BaseModel):
    """Declarative approval contract for a capability."""

    model_config = ConfigDict(extra="forbid")

    required: bool = False
    approver_roles: list[str] = Field(default_factory=list, max_length=20)
    conditions: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("approver_roles", "conditions")
    @classmethod
    def _normalize_unique_string_list(cls, value: list[str]) -> list[str]:
        return _normalize_unique_string_list(value)

    @model_validator(mode="after")
    def _require_approval_detail_when_required(self) -> CapabilityApprovalRequirements:
        if self.required and not self.approver_roles and not self.conditions:
            raise ValueError("approval requirements need approver roles or conditions when required")
        return self


class CapabilityCreate(BaseModel):
    """Create a declarative capability registry record.

    The record is metadata only. Creating it must not register handlers, enqueue
    tasks, dispatch workers, or change runtime orchestration.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    version: str = Field(default="1.0.0", min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=2000)
    supported_task_types: list[str] = Field(min_length=1, max_length=50)
    input_schema_hints: dict[str, Any] = Field(default_factory=dict)
    output_schema_hints: dict[str, Any] = Field(default_factory=dict)
    required_permissions: list[str] = Field(default_factory=list, max_length=50)
    required_tools: list[str] = Field(default_factory=list, max_length=50)
    risk_level: CapabilityRiskLevel = "medium"
    approval_requirements: CapabilityApprovalRequirements = Field(default_factory=CapabilityApprovalRequirements)
    evidence_expectations: list[str] = Field(default_factory=list, max_length=50)
    execution_constraints: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    scope: CapabilityScope = "tenant"

    @field_validator("name", "version", "description")
    @classmethod
    def _normalize_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text fields must be non-empty")
        return value

    @field_validator("supported_task_types", "required_permissions", "required_tools", "evidence_expectations")
    @classmethod
    def _normalize_unique_string_list(cls, value: list[str]) -> list[str]:
        return _normalize_unique_string_list(value)


class CapabilityUpdate(BaseModel):
    """Update mutable capability contract fields without runtime side effects."""

    model_config = ConfigDict(extra="forbid")

    description: str | None = Field(default=None, min_length=1, max_length=2000)
    supported_task_types: list[str] | None = Field(default=None, min_length=1, max_length=50)
    input_schema_hints: dict[str, Any] | None = None
    output_schema_hints: dict[str, Any] | None = None
    required_permissions: list[str] | None = Field(default=None, max_length=50)
    required_tools: list[str] | None = Field(default=None, max_length=50)
    risk_level: CapabilityRiskLevel | None = None
    approval_requirements: CapabilityApprovalRequirements | None = None
    evidence_expectations: list[str] | None = Field(default=None, max_length=50)
    execution_constraints: dict[str, Any] | None = None
    enabled: bool | None = None

    @field_validator("description")
    @classmethod
    def _normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("description must be non-empty when provided")
        return value

    @field_validator("supported_task_types", "required_permissions", "required_tools", "evidence_expectations")
    @classmethod
    def _normalize_optional_unique_string_list(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return _normalize_unique_string_list(value)


class CapabilityRead(BaseModel):
    """Capability registry response contract."""

    capability_id: UUID
    tenant_id: str | None
    scope: CapabilityScope
    name: str
    version: str
    description: str
    supported_task_types: list[str]
    input_schema_hints: dict[str, Any]
    output_schema_hints: dict[str, Any]
    required_permissions: list[str]
    required_tools: list[str]
    risk_level: str
    approval_requirements: dict[str, Any]
    evidence_expectations: list[str]
    execution_constraints: dict[str, Any]
    enabled: bool
    schema_version: int
    created_at: str
    updated_at: str


class CapabilityListRead(BaseModel):
    capabilities: list[CapabilityRead]


def _normalize_unique_string_list(value: list[str]) -> list[str]:
    normalized = [item.strip() for item in value]
    if any(not item for item in normalized):
        raise ValueError("list entries must be non-empty strings")
    if len(set(normalized)) != len(normalized):
        raise ValueError("list entries must be unique")
    return normalized


def _isoformat(value: datetime) -> str:
    return value.isoformat()


def _capability_to_read(capability: Capability) -> CapabilityRead:
    return CapabilityRead(
        capability_id=capability.id,
        tenant_id=capability.tenant_id,
        scope="global" if capability.tenant_id is None else "tenant",
        name=capability.name,
        version=capability.version,
        description=capability.description,
        supported_task_types=capability.supported_task_types,
        input_schema_hints=capability.input_schema_hints,
        output_schema_hints=capability.output_schema_hints,
        required_permissions=capability.required_permissions,
        required_tools=capability.required_tools,
        risk_level=capability.risk_level,
        approval_requirements=capability.approval_requirements,
        evidence_expectations=capability.evidence_expectations,
        execution_constraints=capability.execution_constraints,
        enabled=capability.enabled,
        schema_version=capability.schema_version,
        created_at=_isoformat(capability.created_at),
        updated_at=_isoformat(capability.updated_at),
    )


@router.post("", response_model=CapabilityRead, status_code=status.HTTP_201_CREATED)
def create_capability(
    body: CapabilityCreate,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> CapabilityRead:
    """Persist a declarative capability contract without queue/runtime effects."""
    if body.scope == "global":
        raise HTTPException(status_code=403, detail="global capabilities are read-only from tenant routes")

    tenant_scope = str(tenant_id)
    repo = CapabilityRepository(db)
    if repo.get_conflict_for_scope(name=body.name, version=body.version, tenant_id=tenant_scope) is not None:
        raise HTTPException(status_code=409, detail="capability already exists for scope and version")

    capability = repo.add(
        Capability(
            tenant_id=tenant_scope,
            name=body.name,
            version=body.version,
            description=body.description,
            supported_task_types=body.supported_task_types,
            input_schema_hints=body.input_schema_hints,
            output_schema_hints=body.output_schema_hints,
            required_permissions=body.required_permissions,
            required_tools=body.required_tools,
            risk_level=body.risk_level,
            approval_requirements=body.approval_requirements.model_dump(),
            evidence_expectations=body.evidence_expectations,
            execution_constraints=body.execution_constraints,
            enabled=body.enabled,
            schema_version=CAPABILITY_REGISTRY_SCHEMA_VERSION,
        )
    )
    return _capability_to_read(capability)


@router.get("", response_model=CapabilityListRead)
def list_capabilities(
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> CapabilityListRead:
    """List tenant-visible capability contracts, including global records."""
    capabilities = CapabilityRepository(db).list_visible_for_tenant(tenant_id=str(tenant_id))
    return CapabilityListRead(capabilities=[_capability_to_read(capability) for capability in capabilities])


@router.get("/{capability_id}", response_model=CapabilityRead)
def read_capability(
    capability_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> CapabilityRead:
    """Read one tenant-visible capability contract."""
    capability = CapabilityRepository(db).get_visible_for_tenant(capability_id=capability_id, tenant_id=str(tenant_id))
    if capability is None:
        raise HTTPException(status_code=404, detail="capability not found for tenant")
    return _capability_to_read(capability)


@router.patch("/{capability_id}", response_model=CapabilityRead)
def update_capability(
    capability_id: UUID,
    body: CapabilityUpdate,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> CapabilityRead:
    """Update a tenant-owned capability contract without runtime side effects."""
    repo = CapabilityRepository(db)
    capability = repo.get_visible_for_tenant(capability_id=capability_id, tenant_id=str(tenant_id))
    if capability is None:
        raise HTTPException(status_code=404, detail="capability not found for tenant")
    if capability.tenant_id is None:
        raise HTTPException(status_code=403, detail="global capabilities are read-only from tenant routes")

    updates = body.model_dump(exclude_unset=True)
    if "approval_requirements" in updates and body.approval_requirements is not None:
        updates["approval_requirements"] = body.approval_requirements.model_dump()
    for field_name, value in updates.items():
        setattr(capability, field_name, value)

    return _capability_to_read(repo.update(capability))
