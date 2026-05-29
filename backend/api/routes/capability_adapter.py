from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.domain.capability import Capability
from backend.domain.capability_adapter import CAPABILITY_ADAPTER_SCHEMA_VERSION, CapabilityAdapter
from backend.repositories.capability_adapter_repository import CapabilityAdapterRepository
from backend.repositories.capability_repository import CapabilityRepository
from backend.services.capability_adapter_compatibility import (
    CapabilityAdapterCompatibilityError,
    CapabilityAdapterDeclaration,
    validate_capability_adapter_compatibility,
)

router = APIRouter(prefix="/capability-adapters", tags=["capability-adapters"])

AdapterRiskLevel = Literal["low", "medium", "high", "critical"]
AdapterScope = Literal["tenant", "global"]
AdapterExecutionMode = Literal["declarative", "manual", "synchronous", "asynchronous", "queued"]
AdapterSideEffectClassification = Literal[
    "none",
    "read_only",
    "idempotent_write",
    "non_idempotent_write",
    "external_side_effect",
]


class AdapterApprovalRequirements(BaseModel):
    """Declarative approval contract for a capability adapter."""

    model_config = ConfigDict(extra="forbid")

    required: bool = False
    approver_roles: list[str] = Field(default_factory=list, max_length=20)
    conditions: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("approver_roles", "conditions")
    @classmethod
    def _normalize_unique_string_list(cls, value: list[str]) -> list[str]:
        return _normalize_unique_string_list(value)

    @model_validator(mode="after")
    def _require_approval_detail_when_required(self) -> AdapterApprovalRequirements:
        if self.required and not self.approver_roles and not self.conditions:
            raise ValueError("approval requirements need approver roles or conditions when required")
        return self


class CapabilityAdapterCreate(BaseModel):
    """Create a declarative capability execution adapter contract.

    The record is metadata only. Creating it must not register handlers, enqueue
    tasks, create execution tasks, dispatch workers, or invoke runtime services.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    version: str = Field(default="1.0.0", min_length=1, max_length=64)
    capability_id: UUID | None = None
    capability_name: str | None = Field(default=None, min_length=1, max_length=160)
    capability_version: str | None = Field(default=None, min_length=1, max_length=64)
    supported_task_types: list[str] = Field(min_length=1, max_length=50)
    input_contract: dict[str, Any] = Field(default_factory=dict)
    output_contract: dict[str, Any] = Field(default_factory=dict)
    required_permissions: list[str] = Field(default_factory=list, max_length=50)
    required_tools: list[str] = Field(default_factory=list, max_length=50)
    execution_mode: AdapterExecutionMode = "declarative"
    risk_level: AdapterRiskLevel = "medium"
    approval_requirements: AdapterApprovalRequirements = Field(default_factory=AdapterApprovalRequirements)
    evidence_expectations: list[str] = Field(default_factory=list, max_length=50)
    timeout_retry_hints: dict[str, Any] = Field(default_factory=dict)
    idempotency_expectations: dict[str, Any] = Field(default_factory=dict)
    side_effect_classification: AdapterSideEffectClassification = "none"
    enabled: bool = True
    scope: AdapterScope = "tenant"

    @field_validator("name", "version")
    @classmethod
    def _normalize_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text fields must be non-empty")
        return value

    @field_validator("capability_name", "capability_version")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("capability binding text fields must be non-empty when provided")
        return value

    @field_validator("supported_task_types", "required_permissions", "required_tools", "evidence_expectations")
    @classmethod
    def _normalize_unique_string_list(cls, value: list[str]) -> list[str]:
        return _normalize_unique_string_list(value)

    @model_validator(mode="after")
    def _require_capability_binding(self) -> CapabilityAdapterCreate:
        has_name = self.capability_name is not None
        has_version = self.capability_version is not None
        if has_name != has_version:
            raise ValueError("capability name/version binding requires both capability_name and capability_version")
        if self.capability_id is None and not has_name:
            raise ValueError("capability adapter requires capability_id or capability_name/capability_version binding")
        return self


class CapabilityAdapterUpdate(BaseModel):
    """Update mutable adapter contract fields without runtime side effects."""

    model_config = ConfigDict(extra="forbid")

    capability_id: UUID | None = None
    capability_name: str | None = Field(default=None, min_length=1, max_length=160)
    capability_version: str | None = Field(default=None, min_length=1, max_length=64)
    supported_task_types: list[str] | None = Field(default=None, min_length=1, max_length=50)
    input_contract: dict[str, Any] | None = None
    output_contract: dict[str, Any] | None = None
    required_permissions: list[str] | None = Field(default=None, max_length=50)
    required_tools: list[str] | None = Field(default=None, max_length=50)
    execution_mode: AdapterExecutionMode | None = None
    risk_level: AdapterRiskLevel | None = None
    approval_requirements: AdapterApprovalRequirements | None = None
    evidence_expectations: list[str] | None = Field(default=None, max_length=50)
    timeout_retry_hints: dict[str, Any] | None = None
    idempotency_expectations: dict[str, Any] | None = None
    side_effect_classification: AdapterSideEffectClassification | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def _reject_explicit_null_patch_values(self) -> CapabilityAdapterUpdate:
        null_fields = [field for field in self.model_fields_set if getattr(self, field) is None]
        if null_fields:
            joined_fields = ", ".join(sorted(null_fields))
            raise ValueError(f"capability adapter patch fields cannot be null: {joined_fields}")
        return self

    @field_validator("capability_name", "capability_version")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("capability binding text fields must be non-empty when provided")
        return value

    @field_validator("supported_task_types", "required_permissions", "required_tools", "evidence_expectations")
    @classmethod
    def _normalize_optional_unique_string_list(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return _normalize_unique_string_list(value)

    @model_validator(mode="after")
    def _require_complete_capability_name_version_binding(self) -> CapabilityAdapterUpdate:
        has_name = "capability_name" in self.model_fields_set
        has_version = "capability_version" in self.model_fields_set
        if has_name != has_version:
            raise ValueError(
                "capability name/version binding updates require both capability_name and capability_version"
            )
        return self


class CapabilityAdapterRead(BaseModel):
    """Capability execution adapter response contract."""

    adapter_id: UUID
    tenant_id: str | None
    scope: AdapterScope
    name: str
    version: str
    capability_id: UUID | None
    capability_name: str | None
    capability_version: str | None
    supported_task_types: list[str]
    input_contract: dict[str, Any]
    output_contract: dict[str, Any]
    required_permissions: list[str]
    required_tools: list[str]
    execution_mode: str
    risk_level: str
    approval_requirements: dict[str, Any]
    evidence_expectations: list[str]
    timeout_retry_hints: dict[str, Any]
    idempotency_expectations: dict[str, Any]
    side_effect_classification: str
    enabled: bool
    schema_version: int
    created_at: str
    updated_at: str


class CapabilityAdapterListRead(BaseModel):
    adapters: list[CapabilityAdapterRead]


def _normalize_unique_string_list(value: list[str]) -> list[str]:
    normalized = [item.strip() for item in value]
    if any(not item for item in normalized):
        raise ValueError("list entries must be non-empty strings")
    if len(set(normalized)) != len(normalized):
        raise ValueError("list entries must be unique")
    return normalized


def _isoformat(value: datetime) -> str:
    return value.isoformat()


def _adapter_to_read(adapter: CapabilityAdapter) -> CapabilityAdapterRead:
    return CapabilityAdapterRead(
        adapter_id=adapter.id,
        tenant_id=adapter.tenant_id,
        scope="global" if adapter.tenant_id is None else "tenant",
        name=adapter.name,
        version=adapter.version,
        capability_id=adapter.capability_id,
        capability_name=adapter.capability_name,
        capability_version=adapter.capability_version,
        supported_task_types=adapter.supported_task_types,
        input_contract=adapter.input_contract,
        output_contract=adapter.output_contract,
        required_permissions=adapter.required_permissions,
        required_tools=adapter.required_tools,
        execution_mode=adapter.execution_mode,
        risk_level=adapter.risk_level,
        approval_requirements=adapter.approval_requirements,
        evidence_expectations=adapter.evidence_expectations,
        timeout_retry_hints=adapter.timeout_retry_hints,
        idempotency_expectations=adapter.idempotency_expectations,
        side_effect_classification=adapter.side_effect_classification,
        enabled=adapter.enabled,
        schema_version=adapter.schema_version,
        created_at=_isoformat(adapter.created_at),
        updated_at=_isoformat(adapter.updated_at),
    )


def _resolve_visible_capability_reference(
    *, adapter: CapabilityAdapterDeclaration, tenant_id: str, capability_repo: CapabilityRepository
) -> Capability:
    capability = None
    if adapter.capability_id is not None:
        capability = capability_repo.get_visible_for_tenant(capability_id=adapter.capability_id, tenant_id=tenant_id)
    elif adapter.capability_name is not None and adapter.capability_version is not None:
        capability = capability_repo.get_visible_by_name_version(
            name=adapter.capability_name,
            version=adapter.capability_version,
            tenant_id=tenant_id,
        )

    if capability is None:
        raise HTTPException(status_code=422, detail="referenced capability is not visible to tenant")

    try:
        validate_capability_adapter_compatibility(adapter=adapter, capability=capability)
    except CapabilityAdapterCompatibilityError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"capability adapter is incompatible with referenced capability: {exc}",
        ) from exc

    return capability


def _adapter_candidate(adapter: CapabilityAdapter, updates: dict[str, Any]) -> SimpleNamespace:
    fields = (
        "capability_id",
        "capability_name",
        "capability_version",
        "supported_task_types",
        "risk_level",
        "approval_requirements",
        "side_effect_classification",
        "enabled",
    )
    values = {field: getattr(adapter, field) for field in fields}
    values.update({field: value for field, value in updates.items() if field in values})
    return SimpleNamespace(**values)


@router.post("", response_model=CapabilityAdapterRead, status_code=status.HTTP_201_CREATED)
def create_capability_adapter(
    body: CapabilityAdapterCreate,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> CapabilityAdapterRead:
    """Persist a declarative capability adapter contract without runtime effects."""
    if body.scope == "global":
        raise HTTPException(status_code=403, detail="global capability adapters are read-only from tenant routes")

    tenant_scope = str(tenant_id)
    adapter_repo = CapabilityAdapterRepository(db)
    if adapter_repo.get_conflict_for_scope(name=body.name, version=body.version, tenant_id=tenant_scope) is not None:
        raise HTTPException(status_code=409, detail="capability adapter already exists for scope and version")

    adapter_contract = CapabilityAdapter(
        tenant_id=tenant_scope,
        name=body.name,
        version=body.version,
        capability_id=body.capability_id,
        capability_name=body.capability_name,
        capability_version=body.capability_version,
        supported_task_types=body.supported_task_types,
        input_contract=body.input_contract,
        output_contract=body.output_contract,
        required_permissions=body.required_permissions,
        required_tools=body.required_tools,
        execution_mode=body.execution_mode,
        risk_level=body.risk_level,
        approval_requirements=body.approval_requirements.model_dump(),
        evidence_expectations=body.evidence_expectations,
        timeout_retry_hints=body.timeout_retry_hints,
        idempotency_expectations=body.idempotency_expectations,
        side_effect_classification=body.side_effect_classification,
        enabled=body.enabled,
        schema_version=CAPABILITY_ADAPTER_SCHEMA_VERSION,
    )
    _resolve_visible_capability_reference(
        adapter=adapter_contract,
        tenant_id=tenant_scope,
        capability_repo=CapabilityRepository(db),
    )

    adapter = adapter_repo.add(adapter_contract)
    return _adapter_to_read(adapter)


@router.get("", response_model=CapabilityAdapterListRead)
def list_capability_adapters(
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> CapabilityAdapterListRead:
    """List tenant-visible capability adapter contracts, including global records."""
    adapters = CapabilityAdapterRepository(db).list_visible_for_tenant(tenant_id=str(tenant_id))
    return CapabilityAdapterListRead(adapters=[_adapter_to_read(adapter) for adapter in adapters])


@router.get("/{adapter_id}", response_model=CapabilityAdapterRead)
def read_capability_adapter(
    adapter_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> CapabilityAdapterRead:
    """Read one tenant-visible capability adapter contract."""
    adapter = CapabilityAdapterRepository(db).get_visible_for_tenant(adapter_id=adapter_id, tenant_id=str(tenant_id))
    if adapter is None:
        raise HTTPException(status_code=404, detail="capability adapter not found for tenant")
    return _adapter_to_read(adapter)


@router.patch("/{adapter_id}", response_model=CapabilityAdapterRead)
def update_capability_adapter(
    adapter_id: UUID,
    body: CapabilityAdapterUpdate,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> CapabilityAdapterRead:
    """Update a tenant-owned capability adapter contract without runtime side effects."""
    tenant_scope = str(tenant_id)
    adapter_repo = CapabilityAdapterRepository(db)
    adapter = adapter_repo.get_visible_for_tenant(adapter_id=adapter_id, tenant_id=tenant_scope)
    if adapter is None:
        raise HTTPException(status_code=404, detail="capability adapter not found for tenant")
    if adapter.tenant_id is None:
        raise HTTPException(status_code=403, detail="global capability adapters are read-only from tenant routes")

    updates = body.model_dump(exclude_unset=True)
    if "approval_requirements" in updates and body.approval_requirements is not None:
        updates["approval_requirements"] = body.approval_requirements.model_dump()

    _resolve_visible_capability_reference(
        adapter=_adapter_candidate(adapter, updates),
        tenant_id=tenant_scope,
        capability_repo=CapabilityRepository(db),
    )

    for field_name, value in updates.items():
        setattr(adapter, field_name, value)

    return _adapter_to_read(adapter_repo.update(adapter))
