from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from backend.api.routes._authorization import require_route_permission
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.auth.permissions import Permission
from backend.domain.business_profile import (
    BUSINESS_PROFILE_SCHEMA_VERSION,
    BUSINESS_PROFILE_SUGGESTION_SCHEMA_VERSION,
    BusinessProfile,
    BusinessProfileSuggestion,
)
from backend.repositories.business_profile_repository import BusinessProfileRepository

router = APIRouter(prefix="/business-profile", tags=["business-profile"])

SuggestionStatus = Literal["pending", "approved", "edited", "declined", "dismissed", "superseded"]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _actor_id(request: Request) -> str:
    principal = getattr(request.state, "principal", None)
    subject_id = getattr(principal, "subject_id", None)
    return str(subject_id or "unknown")


def _normalize_category(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("category must be non-empty")
    return value


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


class BusinessProfileSuggestionCreate(BaseModel):
    """Create a tenant-owned suggestion without mutating approved Business Profile truth."""

    model_config = ConfigDict(extra="forbid")

    suggested_category: str = Field(min_length=1, max_length=96)
    suggested_fact: dict[str, Any] = Field(min_length=1)
    rationale: str = Field(min_length=1, max_length=500)
    source_context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("suggested_category", "rationale")
    @classmethod
    def _normalize_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text fields must be non-empty")
        return value


class BusinessProfileSuggestionResolveWithEdit(BaseModel):
    """Approve a pending suggestion with a user-approved edited fact."""

    model_config = ConfigDict(extra="forbid")

    approved_fact: dict[str, Any] = Field(min_length=1)


class BusinessProfileSuggestionRead(BaseModel):
    """Business Profile suggestion lifecycle response contract."""

    suggestion_id: UUID
    tenant_id: str
    profile_id: UUID | None
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


def _get_or_create_active_profile(repo: BusinessProfileRepository, *, tenant_id: str) -> BusinessProfile:
    profile = repo.get_active_profile_for_tenant(tenant_id=tenant_id)
    if profile is not None:
        return profile
    return repo.add_profile(
        BusinessProfile(
            tenant_id=tenant_id,
            approved_facts={},
            provenance={},
            schema_version=BUSINESS_PROFILE_SCHEMA_VERSION,
        )
    )


def _get_pending_suggestion_or_404(
    repo: BusinessProfileRepository, *, suggestion_id: UUID, tenant_id: str
) -> BusinessProfileSuggestion:
    suggestion = repo.get_suggestion_for_tenant(suggestion_id=suggestion_id, tenant_id=tenant_id)
    if suggestion is None:
        raise HTTPException(status_code=404, detail="business profile suggestion not found for tenant")
    return suggestion


def _resolve_value_error(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


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
    repo = BusinessProfileRepository(db)
    profile = _get_or_create_active_profile(repo, tenant_id=tenant_scope)
    try:
        updated = repo.upsert_approved_fact(
            profile=profile,
            category=_normalize_category(category),
            approved_fact=body.approved_fact,
            actor_id=_actor_id(request),
            updated_at=_utcnow(),
            provenance_metadata=body.provenance_metadata,
        )
    except ValueError as exc:
        raise _resolve_value_error(exc) from exc
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
    repo = BusinessProfileRepository(db)
    profile = repo.get_active_profile_for_tenant(tenant_id=tenant_scope)
    suggestion = repo.add_suggestion(
        BusinessProfileSuggestion(
            tenant_id=tenant_scope,
            profile_id=profile.id if profile else None,
            suggested_category=body.suggested_category,
            suggested_fact=body.suggested_fact,
            rationale=body.rationale,
            source_context=body.source_context,
            schema_version=BUSINESS_PROFILE_SUGGESTION_SCHEMA_VERSION,
        )
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
            actor_id=_actor_id(request),
        )
    except ValueError as exc:
        raise _resolve_value_error(exc) from exc
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
            actor_id=_actor_id(request),
        )
    except ValueError as exc:
        raise _resolve_value_error(exc) from exc
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
    repo = BusinessProfileRepository(db)
    suggestion = _get_pending_suggestion_or_404(repo, suggestion_id=suggestion_id, tenant_id=tenant_scope)
    try:
        updated_suggestion = repo.decline_suggestion(
            suggestion=suggestion,
            resolved_at=_utcnow(),
            actor_id=_actor_id(request),
        )
    except ValueError as exc:
        raise _resolve_value_error(exc) from exc
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
    repo = BusinessProfileRepository(db)
    suggestion = _get_pending_suggestion_or_404(repo, suggestion_id=suggestion_id, tenant_id=tenant_scope)
    try:
        updated_suggestion = repo.dismiss_suggestion(
            suggestion=suggestion,
            resolved_at=_utcnow(),
            actor_id=_actor_id(request),
        )
    except ValueError as exc:
        raise _resolve_value_error(exc) from exc
    return BusinessProfileSuggestionResolutionRead(profile=None, suggestion=_suggestion_to_read(updated_suggestion))
