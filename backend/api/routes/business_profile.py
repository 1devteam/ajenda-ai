from __future__ import annotations

import json
import logging
import re
import uuid as _uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from backend.api.routes._authorization import require_route_permission
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.auth.permissions import Permission
from backend.domain.audit_event import AuditEvent
from backend.domain.business_profile import (
    BUSINESS_PROFILE_SCHEMA_VERSION,
    BUSINESS_PROFILE_SUGGESTION_SCHEMA_VERSION,
    BusinessProfile,
    BusinessProfileSuggestion,
)
from backend.repositories.audit_event_repository import AuditEventRepository
from backend.repositories.business_profile_repository import BusinessProfileRepository
from backend.repositories.mission_repository import MissionRepository

router = APIRouter(prefix="/business-profile", tags=["business-profile"])
logger = logging.getLogger("ajenda.business_profile")

SuggestionStatus = Literal["pending", "approved", "edited", "declined", "dismissed", "superseded"]

MAX_PROFILE_JSON_DEPTH = 8
MAX_PROFILE_JSON_BYTES = 16_384
MAX_PROFILE_CATEGORY_LENGTH = 96
_CATEGORY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,95}$")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _actor_id(request: Request) -> str:
    principal = getattr(request.state, "principal", None)
    subject_id = getattr(principal, "subject_id", None)
    return str(subject_id or "unknown")


def _normalize_category(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("category must be non-empty")
    if len(normalized) > MAX_PROFILE_CATEGORY_LENGTH:
        raise ValueError(f"category must be at most {MAX_PROFILE_CATEGORY_LENGTH} characters")
    if not _CATEGORY_PATTERN.fullmatch(normalized):
        raise ValueError("category must use lowercase letters, numbers, underscores, periods, colons, or hyphens")
    return normalized


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


def _validate_bounded_json_object(value: dict[str, Any], *, field_name: str) -> dict[str, Any]:
    if _json_depth(value) > MAX_PROFILE_JSON_DEPTH:
        raise ValueError(f"{field_name} exceeds maximum JSON depth of {MAX_PROFILE_JSON_DEPTH}")
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be JSON serializable") from exc
    if len(encoded.encode("utf-8")) > MAX_PROFILE_JSON_BYTES:
        raise ValueError(f"{field_name} exceeds maximum JSON size of {MAX_PROFILE_JSON_BYTES} bytes")
    return value


def _extract_source_context_mission_id(source_context: dict[str, Any]) -> UUID | None:
    raw = source_context.get("mission_id")
    if raw is None:
        return None
    try:
        return UUID(str(raw))
    except ValueError as exc:
        raise ValueError("source_context.mission_id must be a valid UUID when present") from exc


class BusinessProfileRead(BaseModel):
    """Stable read shape for Mission Brief consumers of approved profile facts."""

    profile_id: UUID | None
    tenant_id: str
    status: str
    approved_facts: dict[str, Any]
    provenance: dict[str, Any]
    schema_version: int
    created_at: str | None
    updated_at: str | None


class BusinessProfileFactUpsert(BaseModel):
    """Explicit approved-fact write request; no profile truth is inferred silently."""

    model_config = ConfigDict(extra="forbid")

    approved_fact: dict[str, Any] = Field(min_length=1)
    provenance_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("approved_fact", "provenance_metadata")
    @classmethod
    def _validate_json_payloads(cls, value: dict[str, Any], info: Any) -> dict[str, Any]:
        return _validate_bounded_json_object(value, field_name=info.field_name)


class BusinessProfileSuggestionCreate(BaseModel):
    """Create a tenant-owned suggestion without mutating approved Business Profile truth."""

    model_config = ConfigDict(extra="forbid")

    suggested_category: str = Field(min_length=1, max_length=MAX_PROFILE_CATEGORY_LENGTH)
    suggested_fact: dict[str, Any] = Field(min_length=1)
    rationale: str = Field(min_length=1, max_length=500)
    source_context: dict[str, Any] = Field(default_factory=dict)
    mission_id: UUID | None = None

    @field_validator("suggested_category")
    @classmethod
    def _normalize_suggested_category(cls, value: str) -> str:
        return _normalize_category(value)

    @field_validator("rationale")
    @classmethod
    def _normalize_rationale(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text fields must be non-empty")
        return value

    @field_validator("suggested_fact", "source_context")
    @classmethod
    def _validate_json_payloads(cls, value: dict[str, Any], info: Any) -> dict[str, Any]:
        return _validate_bounded_json_object(value, field_name=info.field_name)

    @model_validator(mode="after")
    def _validate_mission_id_consistency(self) -> BusinessProfileSuggestionCreate:
        source_context_mission_id = _extract_source_context_mission_id(self.source_context)
        if (
            self.mission_id is not None
            and source_context_mission_id is not None
            and self.mission_id != source_context_mission_id
        ):
            raise ValueError("mission_id must match source_context.mission_id when both are provided")
        return self


class BusinessProfileSuggestionResolveWithEdit(BaseModel):
    """Approve a pending suggestion with a user-approved edited fact."""

    model_config = ConfigDict(extra="forbid")

    approved_fact: dict[str, Any] = Field(min_length=1)

    @field_validator("approved_fact")
    @classmethod
    def _validate_json_payload(cls, value: dict[str, Any], info: Any) -> dict[str, Any]:
        return _validate_bounded_json_object(value, field_name=info.field_name)


class BusinessProfileSuggestionRead(BaseModel):
    """Business Profile suggestion lifecycle response contract."""

    suggestion_id: UUID
    tenant_id: str
    profile_id: UUID | None
    mission_id: UUID | None
    suggested_category: str
    suggested_fact: dict[str, Any]
    rationale: str
    source_context: dict[str, Any]
    status: str
    resolution: dict[str, Any]
    schema_version: int
    created_at: str
    resolved_at: str | None


class BusinessProfileSuggestionListRead(BaseModel):
    """List response for tenant-owned Business Profile suggestions."""

    suggestions: list[BusinessProfileSuggestionRead]


class BusinessProfileSuggestionResolutionRead(BaseModel):
    """Suggestion resolution response, including profile truth when promoted."""

    profile: BusinessProfileRead | None = None
    suggestion: BusinessProfileSuggestionRead


class BusinessProfileHistoryEntryRead(BaseModel):
    """Audit/history entry for profile fact mutations and suggestion decisions."""

    entry_type: Literal["profile_fact", "suggestion_decision"]
    category: str
    actor_id: str | None = None
    decision: str | None = None
    suggestion_id: UUID | None = None
    mission_id: UUID | None = None
    current_fact: dict[str, Any] | None = None
    superseded_fact: dict[str, Any] | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    occurred_at: str | None = None


class BusinessProfileHistoryRead(BaseModel):
    """Tenant-scoped profile history/audit read surface."""

    profile: BusinessProfileRead
    entries: list[BusinessProfileHistoryEntryRead]
    suggestions: list[BusinessProfileSuggestionRead]


def _profile_to_read(profile: BusinessProfile | None, *, tenant_id: str) -> BusinessProfileRead:
    if profile is None:
        return BusinessProfileRead(
            profile_id=None,
            tenant_id=tenant_id,
            status="missing",
            approved_facts={},
            provenance={},
            schema_version=BUSINESS_PROFILE_SCHEMA_VERSION,
            created_at=None,
            updated_at=None,
        )
    return BusinessProfileRead(
        profile_id=profile.id,
        tenant_id=profile.tenant_id,
        status=profile.status,
        approved_facts=profile.approved_facts,
        provenance=profile.provenance,
        schema_version=profile.schema_version,
        created_at=profile.created_at.isoformat(),
        updated_at=profile.updated_at.isoformat(),
    )


def _suggestion_to_read(suggestion: BusinessProfileSuggestion) -> BusinessProfileSuggestionRead:
    return BusinessProfileSuggestionRead(
        suggestion_id=suggestion.id,
        tenant_id=suggestion.tenant_id,
        profile_id=suggestion.profile_id,
        mission_id=suggestion.mission_id,
        suggested_category=suggestion.suggested_category,
        suggested_fact=suggestion.suggested_fact,
        rationale=suggestion.rationale,
        source_context=suggestion.source_context,
        status=suggestion.status,
        resolution=suggestion.resolution,
        schema_version=suggestion.schema_version,
        created_at=suggestion.created_at.isoformat(),
        resolved_at=suggestion.resolved_at.isoformat() if suggestion.resolved_at else None,
    )


def _history_entries(
    profile: BusinessProfile | None, suggestions: list[BusinessProfileSuggestion]
) -> list[BusinessProfileHistoryEntryRead]:
    entries: list[BusinessProfileHistoryEntryRead] = []
    if profile is not None:
        approved_facts = profile.approved_facts or {}
        provenance = profile.provenance or {}
        for category in sorted(set(approved_facts) | set(provenance)):
            provenance_entry = provenance.get(category) or {}
            suggestion_id: UUID | None = None
            if provenance_entry.get("suggestion_id"):
                suggestion_id = UUID(str(provenance_entry["suggestion_id"]))
            entries.append(
                BusinessProfileHistoryEntryRead(
                    entry_type="profile_fact",
                    category=category,
                    actor_id=provenance_entry.get("actor_id"),
                    decision=provenance_entry.get("decision"),
                    suggestion_id=suggestion_id,
                    current_fact=approved_facts.get(category),
                    superseded_fact=provenance_entry.get("superseded_fact"),
                    provenance=provenance_entry,
                    occurred_at=provenance_entry.get("updated_at") or provenance_entry.get("resolved_at"),
                )
            )
    for suggestion in suggestions:
        if suggestion.status == "pending":
            continue
        entries.append(
            BusinessProfileHistoryEntryRead(
                entry_type="suggestion_decision",
                category=suggestion.suggested_category,
                actor_id=(suggestion.resolution or {}).get("actor_id"),
                decision=(suggestion.resolution or {}).get("decision") or suggestion.status,
                suggestion_id=suggestion.id,
                mission_id=suggestion.mission_id,
                current_fact=(suggestion.resolution or {}).get("approved_fact"),
                superseded_fact=(suggestion.resolution or {}).get("superseded_fact"),
                provenance=suggestion.resolution or {},
                occurred_at=suggestion.resolved_at.isoformat() if suggestion.resolved_at else None,
            )
        )
    return sorted(entries, key=lambda entry: entry.occurred_at or "")


def _get_or_create_active_profile(repo: BusinessProfileRepository, *, tenant_id: str) -> BusinessProfile:
    return repo.get_or_create_active_profile(tenant_id=tenant_id, schema_version=BUSINESS_PROFILE_SCHEMA_VERSION)


def _get_pending_suggestion_or_404(
    repo: BusinessProfileRepository, *, suggestion_id: UUID, tenant_id: str
) -> BusinessProfileSuggestion:
    suggestion = repo.get_suggestion_for_tenant(suggestion_id=suggestion_id, tenant_id=tenant_id)
    if suggestion is None:
        raise HTTPException(status_code=404, detail="business profile suggestion not found for tenant")
    return suggestion


def _resolve_value_error(exc: ValueError) -> HTTPException:
    logger.warning("business_profile_validation_failed", extra={"detail": str(exc)})
    return HTTPException(status_code=409, detail=str(exc))


def _validate_mission_link(*, mission_id: UUID | None, tenant_id: str, db: Session) -> None:
    if mission_id is None:
        return
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=tenant_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")


def _append_profile_audit_event(
    *,
    db: Session,
    tenant_id: str,
    actor_id: str,
    action: str,
    profile_id: UUID | None,
    suggestion_id: UUID | None = None,
    mission_id: UUID | None = None,
    category: str | None = None,
    decision: str | None = None,
) -> None:
    AuditEventRepository(db).append(
        AuditEvent(
            tenant_id=tenant_id,
            mission_id=mission_id,
            category="business_profile",
            action=action,
            actor=actor_id,
            details=f"Business Profile {action}",
            payload_json={
                "profile_id": str(profile_id) if profile_id else None,
                "suggestion_id": str(suggestion_id) if suggestion_id else None,
                "category": category,
                "decision": decision,
                "authority_class": "governed_mutation",
                "runtime_side_effects": False,
            },
        )
    )


@router.get("", response_model=BusinessProfileRead)
def read_business_profile(
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> BusinessProfileRead:
    """Read active tenant Business Profile facts without mutating profile truth."""
    require_route_permission(request=request, db=db, permission=Permission.BUSINESS_PROFILE_READ, tenant_id=tenant_id)
    tenant_scope = str(tenant_id)
    profile = BusinessProfileRepository(db).get_active_profile_for_tenant(tenant_id=tenant_scope)
    return _profile_to_read(profile, tenant_id=tenant_scope)


@router.get("/history", response_model=BusinessProfileHistoryRead)
def read_business_profile_history(
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> BusinessProfileHistoryRead:
    """Read tenant-scoped profile history and suggestion decisions without mutating runtime state."""
    require_route_permission(request=request, db=db, permission=Permission.BUSINESS_PROFILE_READ, tenant_id=tenant_id)
    tenant_scope = str(tenant_id)
    repo = BusinessProfileRepository(db)
    profile = repo.get_active_profile_for_tenant(tenant_id=tenant_scope)
    suggestions = repo.list_suggestions_for_tenant(tenant_id=tenant_scope)
    return BusinessProfileHistoryRead(
        profile=_profile_to_read(profile, tenant_id=tenant_scope),
        entries=_history_entries(profile, suggestions),
        suggestions=[_suggestion_to_read(record) for record in suggestions],
    )


@router.put("/facts/{category}", response_model=BusinessProfileRead)
def upsert_business_profile_fact(
    category: str,
    body: BusinessProfileFactUpsert,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> BusinessProfileRead:
    """Explicitly create or update one approved Business Profile fact."""
    require_route_permission(request=request, db=db, permission=Permission.BUSINESS_PROFILE_MANAGE, tenant_id=tenant_id)
    tenant_scope = str(tenant_id)
    actor_id = _actor_id(request)
    repo = BusinessProfileRepository(db)
    profile = _get_or_create_active_profile(repo, tenant_id=tenant_scope)
    normalized_category = _normalize_category(category)
    try:
        updated = repo.upsert_approved_fact(
            profile=profile,
            category=normalized_category,
            approved_fact=body.approved_fact,
            actor_id=actor_id,
            updated_at=_utcnow(),
            provenance_metadata=body.provenance_metadata,
        )
    except ValueError as exc:
        raise _resolve_value_error(exc) from exc
    _append_profile_audit_event(
        db=db,
        tenant_id=tenant_scope,
        actor_id=actor_id,
        action="business_profile_fact_upserted",
        profile_id=updated.id,
        category=normalized_category,
        decision="direct_update",
    )
    return _profile_to_read(updated, tenant_id=tenant_scope)


@router.post("/suggestions", response_model=BusinessProfileSuggestionRead, status_code=status.HTTP_201_CREATED)
def create_business_profile_suggestion(
    body: BusinessProfileSuggestionCreate,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> BusinessProfileSuggestionRead:
    """Create a pending profile update suggestion without promoting durable profile truth."""
    require_route_permission(request=request, db=db, permission=Permission.BUSINESS_PROFILE_MANAGE, tenant_id=tenant_id)
    tenant_scope = str(tenant_id)
    _validate_mission_link(mission_id=body.mission_id, tenant_id=tenant_scope, db=db)
    actor_id = _actor_id(request)
    repo = BusinessProfileRepository(db)
    profile = repo.get_active_profile_for_tenant(tenant_id=tenant_scope)
    suggestion = repo.add_suggestion(
        BusinessProfileSuggestion(
            tenant_id=tenant_scope,
            profile_id=profile.id if profile else None,
            mission_id=body.mission_id,
            suggested_category=body.suggested_category,
            suggested_fact=body.suggested_fact,
            rationale=body.rationale,
            source_context=body.source_context,
            schema_version=BUSINESS_PROFILE_SUGGESTION_SCHEMA_VERSION,
        )
    )
    _append_profile_audit_event(
        db=db,
        tenant_id=tenant_scope,
        actor_id=actor_id,
        action="business_profile_suggestion_created",
        profile_id=profile.id if profile else None,
        suggestion_id=suggestion.id,
        mission_id=body.mission_id,
        category=suggestion.suggested_category,
        decision="pending",
    )
    return _suggestion_to_read(suggestion)


@router.get("/suggestions", response_model=BusinessProfileSuggestionListRead)
def list_business_profile_suggestions(
    request: Request,
    status_filter: SuggestionStatus | None = Query(default=None, alias="status"),
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> BusinessProfileSuggestionListRead:
    """List tenant-owned profile update suggestions, optionally by lifecycle status."""
    require_route_permission(request=request, db=db, permission=Permission.BUSINESS_PROFILE_READ, tenant_id=tenant_id)
    records = BusinessProfileRepository(db).list_suggestions_for_tenant(tenant_id=str(tenant_id), status=status_filter)
    return BusinessProfileSuggestionListRead(suggestions=[_suggestion_to_read(record) for record in records])


@router.post("/suggestions/{suggestion_id}/approve", response_model=BusinessProfileSuggestionResolutionRead)
def approve_business_profile_suggestion(
    suggestion_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> BusinessProfileSuggestionResolutionRead:
    """Approve a pending suggestion as-is and promote that fact to profile truth."""
    require_route_permission(request=request, db=db, permission=Permission.BUSINESS_PROFILE_MANAGE, tenant_id=tenant_id)
    tenant_scope = str(tenant_id)
    actor_id = _actor_id(request)
    repo = BusinessProfileRepository(db)
    suggestion = _get_pending_suggestion_or_404(repo, suggestion_id=suggestion_id, tenant_id=tenant_scope)
    try:
        repo.require_pending_suggestion(suggestion)
    except ValueError as exc:
        raise _resolve_value_error(exc) from exc
    profile = _get_or_create_active_profile(repo, tenant_id=tenant_scope)
    try:
        updated_profile, updated_suggestion = repo.approve_suggestion_as_is(
            profile=profile,
            suggestion=suggestion,
            resolved_at=_utcnow(),
            actor_id=actor_id,
        )
    except ValueError as exc:
        raise _resolve_value_error(exc) from exc
    _append_profile_audit_event(
        db=db,
        tenant_id=tenant_scope,
        actor_id=actor_id,
        action="business_profile_suggestion_resolved",
        profile_id=updated_profile.id,
        suggestion_id=updated_suggestion.id,
        mission_id=updated_suggestion.mission_id,
        category=updated_suggestion.suggested_category,
        decision=updated_suggestion.status,
    )
    return BusinessProfileSuggestionResolutionRead(
        profile=_profile_to_read(updated_profile, tenant_id=tenant_scope),
        suggestion=_suggestion_to_read(updated_suggestion),
    )


@router.post("/suggestions/{suggestion_id}/approve-with-edits", response_model=BusinessProfileSuggestionResolutionRead)
def approve_business_profile_suggestion_with_edits(
    suggestion_id: UUID,
    body: BusinessProfileSuggestionResolveWithEdit,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> BusinessProfileSuggestionResolutionRead:
    """Approve a pending suggestion with edits and store only the edited approved fact."""
    require_route_permission(request=request, db=db, permission=Permission.BUSINESS_PROFILE_MANAGE, tenant_id=tenant_id)
    tenant_scope = str(tenant_id)
    actor_id = _actor_id(request)
    repo = BusinessProfileRepository(db)
    suggestion = _get_pending_suggestion_or_404(repo, suggestion_id=suggestion_id, tenant_id=tenant_scope)
    try:
        repo.require_pending_suggestion(suggestion)
    except ValueError as exc:
        raise _resolve_value_error(exc) from exc
    profile = _get_or_create_active_profile(repo, tenant_id=tenant_scope)
    try:
        updated_profile, updated_suggestion = repo.approve_suggestion_with_edit(
            profile=profile,
            suggestion=suggestion,
            approved_fact=body.approved_fact,
            resolved_at=_utcnow(),
            actor_id=actor_id,
        )
    except ValueError as exc:
        raise _resolve_value_error(exc) from exc
    _append_profile_audit_event(
        db=db,
        tenant_id=tenant_scope,
        actor_id=actor_id,
        action="business_profile_suggestion_resolved",
        profile_id=updated_profile.id,
        suggestion_id=updated_suggestion.id,
        mission_id=updated_suggestion.mission_id,
        category=updated_suggestion.suggested_category,
        decision=updated_suggestion.status,
    )
    return BusinessProfileSuggestionResolutionRead(
        profile=_profile_to_read(updated_profile, tenant_id=tenant_scope),
        suggestion=_suggestion_to_read(updated_suggestion),
    )


@router.post("/suggestions/{suggestion_id}/decline", response_model=BusinessProfileSuggestionResolutionRead)
def decline_business_profile_suggestion(
    suggestion_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> BusinessProfileSuggestionResolutionRead:
    """Decline a pending suggestion without promoting durable profile truth."""
    require_route_permission(request=request, db=db, permission=Permission.BUSINESS_PROFILE_MANAGE, tenant_id=tenant_id)
    tenant_scope = str(tenant_id)
    actor_id = _actor_id(request)
    repo = BusinessProfileRepository(db)
    suggestion = _get_pending_suggestion_or_404(repo, suggestion_id=suggestion_id, tenant_id=tenant_scope)
    try:
        updated_suggestion = repo.decline_suggestion(
            suggestion=suggestion,
            resolved_at=_utcnow(),
            actor_id=actor_id,
        )
    except ValueError as exc:
        raise _resolve_value_error(exc) from exc
    _append_profile_audit_event(
        db=db,
        tenant_id=tenant_scope,
        actor_id=actor_id,
        action="business_profile_suggestion_resolved",
        profile_id=updated_suggestion.profile_id,
        suggestion_id=updated_suggestion.id,
        mission_id=updated_suggestion.mission_id,
        category=updated_suggestion.suggested_category,
        decision=updated_suggestion.status,
    )
    return BusinessProfileSuggestionResolutionRead(profile=None, suggestion=_suggestion_to_read(updated_suggestion))


@router.post("/suggestions/{suggestion_id}/dismiss", response_model=BusinessProfileSuggestionResolutionRead)
def dismiss_business_profile_suggestion(
    suggestion_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> BusinessProfileSuggestionResolutionRead:
    """Dismiss a pending suggestion without promoting durable profile truth."""
    require_route_permission(request=request, db=db, permission=Permission.BUSINESS_PROFILE_MANAGE, tenant_id=tenant_id)
    tenant_scope = str(tenant_id)
    actor_id = _actor_id(request)
    repo = BusinessProfileRepository(db)
    suggestion = _get_pending_suggestion_or_404(repo, suggestion_id=suggestion_id, tenant_id=tenant_scope)
    try:
        updated_suggestion = repo.dismiss_suggestion(
            suggestion=suggestion,
            resolved_at=_utcnow(),
            actor_id=actor_id,
        )
    except ValueError as exc:
        raise _resolve_value_error(exc) from exc
    _append_profile_audit_event(
        db=db,
        tenant_id=tenant_scope,
        actor_id=actor_id,
        action="business_profile_suggestion_resolved",
        profile_id=updated_suggestion.profile_id,
        suggestion_id=updated_suggestion.id,
        mission_id=updated_suggestion.mission_id,
        category=updated_suggestion.suggested_category,
        decision=updated_suggestion.status,
    )
    return BusinessProfileSuggestionResolutionRead(profile=None, suggestion=_suggestion_to_read(updated_suggestion))
