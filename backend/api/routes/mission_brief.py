from __future__ import annotations

import json
import uuid as _uuid
from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from backend.api.routes._authorization import require_route_permission
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.auth.permissions import Permission
from backend.domain.compliance import is_supported_compliance_category, is_supported_jurisdiction
from backend.repositories.business_profile_repository import BusinessProfileRepository
from backend.services.mission_brief_read_model import MISSION_BRIEF_SCHEMA_VERSION, build_mission_brief_read_model

router = APIRouter(prefix="/mission-briefs", tags=["mission-briefs"])

MAX_MISSION_BRIEF_JSON_DEPTH = 8
MAX_MISSION_BRIEF_JSON_BYTES = 16_384


def _json_depth(value: Any, *, depth: int = 0) -> int:
    if isinstance(value, Mapping):
        if not value:
            return depth + 1
        return max(_json_depth(item, depth=depth + 1) for item in value.values())
    if isinstance(value, list):
        if not value:
            return depth + 1
        return max(_json_depth(item, depth=depth + 1) for item in value)
    return depth + 1


def _validate_bounded_json(value: dict[str, Any], *, field_name: str) -> dict[str, Any]:
    if _json_depth(value) > MAX_MISSION_BRIEF_JSON_DEPTH:
        raise ValueError(f"{field_name} exceeds maximum JSON depth of {MAX_MISSION_BRIEF_JSON_DEPTH}")
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be JSON serializable") from exc
    if len(encoded.encode("utf-8")) > MAX_MISSION_BRIEF_JSON_BYTES:
        raise ValueError(f"{field_name} exceeds maximum JSON size of {MAX_MISSION_BRIEF_JSON_BYTES} bytes")
    return value


def _normalize_unique_string_list(value: list[str]) -> list[str]:
    normalized = [item.strip() for item in value]
    if any(not item for item in normalized):
        raise ValueError("list entries must be non-empty strings")
    if len(set(normalized)) != len(normalized):
        raise ValueError("list entries must be unique")
    return normalized


class MissionBriefSuccessCriterion(BaseModel):
    """Mission Brief success criterion supplied by current mission intent."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=1000)
    evidence: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("description")
    @classmethod
    def _normalize_description(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("success criterion description is required")
        return value

    @field_validator("evidence")
    @classmethod
    def _normalize_evidence(cls, value: list[str]) -> list[str]:
        return _normalize_unique_string_list(value)


class MissionBriefConstraint(BaseModel):
    """Mission Brief constraint supplied by current mission intent."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1000)
    hard: bool = True

    @field_validator("name", "description")
    @classmethod
    def _normalize_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("constraint text fields must be non-empty")
        return value


class MissionBriefBudgetLimits(BaseModel):
    """Optional budget defaults for Mission Brief suggested MissionCreate fields."""

    model_config = ConfigDict(extra="forbid")

    max_tasks: int | None = Field(default=None, ge=1)
    max_runtime_minutes: int | None = Field(default=None, ge=1)
    max_cost_usd: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _require_at_least_one_limit(self) -> MissionBriefBudgetLimits:
        if self.max_tasks is None and self.max_runtime_minutes is None and self.max_cost_usd is None:
            raise ValueError("at least one budget limit is required when budget_limits is provided")
        return self


class MissionBriefCurrentIntent(BaseModel):
    """Current mission-specific intent; Business Profile may fill only reusable defaults."""

    model_config = ConfigDict(extra="forbid")

    objective: str | None = Field(default=None, min_length=1, max_length=5000)
    success_criteria: list[MissionBriefSuccessCriterion] | None = Field(default=None, max_length=20)
    constraints: list[MissionBriefConstraint] | None = Field(default=None, max_length=20)
    operator_notes: str | None = Field(default=None, max_length=5000)
    context: dict[str, Any] | None = None
    priority: str | None = Field(default=None, min_length=1, max_length=32)
    approval_required: bool | None = None
    approval_expectations: list[str] | None = Field(default=None, max_length=20)
    budget_limits: MissionBriefBudgetLimits | None = None
    scope_limits: list[str] | None = Field(default=None, max_length=20)
    allowed_actions: list[str] | None = Field(default=None, max_length=50)
    allowed_tools: list[str] | None = Field(default=None, max_length=50)
    compliance_category: str | None = Field(default=None, min_length=1, max_length=64)
    jurisdiction: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("objective", "operator_notes", "priority", "compliance_category", "jurisdiction")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("text fields must be non-empty when provided")
        return value

    @field_validator("approval_expectations", "scope_limits", "allowed_actions", "allowed_tools")
    @classmethod
    def _normalize_string_lists(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return _normalize_unique_string_list(value)

    @field_validator("context")
    @classmethod
    def _validate_context(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        return _validate_bounded_json(value, field_name="current_intent.context")

    @field_validator("compliance_category")
    @classmethod
    def _validate_compliance_category(cls, value: str | None) -> str | None:
        if value is not None and not is_supported_compliance_category(value):
            raise ValueError("unsupported compliance_category")
        return value

    @field_validator("jurisdiction")
    @classmethod
    def _validate_jurisdiction(cls, value: str | None) -> str | None:
        if value is not None and not is_supported_jurisdiction(value):
            raise ValueError("unsupported jurisdiction")
        return value


class MissionBriefDraftRequest(BaseModel):
    """Read-only Mission Brief draft request."""

    model_config = ConfigDict(extra="forbid")

    current_intent: MissionBriefCurrentIntent = Field(default_factory=MissionBriefCurrentIntent)
    request_context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("request_context")
    @classmethod
    def _validate_request_context(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _validate_bounded_json(value, field_name="request_context")


class MissionBriefDraftRead(BaseModel):
    """Read-only Mission Brief draft/readiness response."""

    schema_version: int
    tenant_id: str
    brief: dict[str, Any]
    missing_information: list[dict[str, Any]]
    suggested_mission_create: dict[str, Any]
    provenance: dict[str, Any]
    readiness: dict[str, Any]
    authority_flags: dict[str, Any]


@router.post("/draft", response_model=MissionBriefDraftRead)
def draft_mission_brief(
    body: MissionBriefDraftRequest,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> MissionBriefDraftRead:
    """Draft a read-only Mission Brief without creating missions or runtime work."""
    require_route_permission(request=request, db=db, permission=Permission.MISSION_CREATE, tenant_id=tenant_id)
    require_route_permission(request=request, db=db, permission=Permission.BUSINESS_PROFILE_READ, tenant_id=tenant_id)
    tenant_scope = str(tenant_id)
    profile = BusinessProfileRepository(db).get_active_profile_for_tenant(tenant_id=tenant_scope)
    current_intent = body.current_intent.model_dump(exclude_unset=True, exclude_none=True)
    request_context = body.request_context
    read_model = build_mission_brief_read_model(
        tenant_id=tenant_scope,
        approved_facts=profile.approved_facts if profile is not None else {},
        provenance=profile.provenance if profile is not None else {},
        current_intent=current_intent,
        request_context=request_context,
    )
    read_model["schema_version"] = MISSION_BRIEF_SCHEMA_VERSION
    return MissionBriefDraftRead(**read_model)
