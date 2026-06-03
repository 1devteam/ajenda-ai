from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.business_profile import BusinessProfile, BusinessProfileSuggestion


class BusinessProfileRepository:
    """Persistence contract for tenant-owned Business Profile records and suggestions."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_profile(self, profile: BusinessProfile) -> BusinessProfile:
        self._session.add(profile)
        self._session.flush()
        self._session.refresh(profile)
        return profile

    def get_profile_for_tenant(self, *, profile_id: uuid.UUID, tenant_id: str) -> BusinessProfile | None:
        stmt = select(BusinessProfile).where(BusinessProfile.id == profile_id, BusinessProfile.tenant_id == tenant_id)
        return self._session.scalar(stmt)

    def get_active_profile_for_tenant(self, *, tenant_id: str) -> BusinessProfile | None:
        stmt = select(BusinessProfile).where(
            BusinessProfile.tenant_id == tenant_id,
            BusinessProfile.status == "active",
        )
        return self._session.scalar(stmt)

    def update_profile(self, profile: BusinessProfile) -> BusinessProfile:
        self._session.add(profile)
        self._session.flush()
        self._session.refresh(profile)
        return profile

    def add_suggestion(self, suggestion: BusinessProfileSuggestion) -> BusinessProfileSuggestion:
        self._session.add(suggestion)
        self._session.flush()
        self._session.refresh(suggestion)
        return suggestion

    def get_suggestion_for_tenant(
        self, *, suggestion_id: uuid.UUID, tenant_id: str
    ) -> BusinessProfileSuggestion | None:
        stmt = select(BusinessProfileSuggestion).where(
            BusinessProfileSuggestion.id == suggestion_id,
            BusinessProfileSuggestion.tenant_id == tenant_id,
        )
        return self._session.scalar(stmt)

    def list_suggestions_for_tenant(
        self, *, tenant_id: str, status: str | None = None
    ) -> list[BusinessProfileSuggestion]:
        stmt = select(BusinessProfileSuggestion).where(BusinessProfileSuggestion.tenant_id == tenant_id)
        if status is not None:
            stmt = stmt.where(BusinessProfileSuggestion.status == status)
        stmt = stmt.order_by(BusinessProfileSuggestion.created_at.asc())
        return list(self._session.scalars(stmt))

    def approve_suggestion_as_is(
        self,
        *,
        profile: BusinessProfile,
        suggestion: BusinessProfileSuggestion,
        resolved_at: datetime,
        actor_id: str,
    ) -> tuple[BusinessProfile, BusinessProfileSuggestion]:
        return self._approve_suggestion(
            profile=profile,
            suggestion=suggestion,
            approved_fact=suggestion.suggested_fact,
            resolution_status="approved",
            resolved_at=resolved_at,
            actor_id=actor_id,
        )

    def approve_suggestion_with_edit(
        self,
        *,
        profile: BusinessProfile,
        suggestion: BusinessProfileSuggestion,
        approved_fact: dict[str, object],
        resolved_at: datetime,
        actor_id: str,
    ) -> tuple[BusinessProfile, BusinessProfileSuggestion]:
        return self._approve_suggestion(
            profile=profile,
            suggestion=suggestion,
            approved_fact=approved_fact,
            resolution_status="edited",
            resolved_at=resolved_at,
            actor_id=actor_id,
        )

    def decline_suggestion(
        self,
        *,
        suggestion: BusinessProfileSuggestion,
        resolved_at: datetime,
        actor_id: str,
    ) -> BusinessProfileSuggestion:
        suggestion.status = "declined"
        suggestion.resolved_at = resolved_at
        suggestion.resolution = {"actor_id": actor_id, "decision": "declined"}
        return self._update_suggestion(suggestion)

    def dismiss_suggestion(
        self,
        *,
        suggestion: BusinessProfileSuggestion,
        resolved_at: datetime,
        actor_id: str,
    ) -> BusinessProfileSuggestion:
        suggestion.status = "dismissed"
        suggestion.resolved_at = resolved_at
        suggestion.resolution = {"actor_id": actor_id, "decision": "dismissed"}
        return self._update_suggestion(suggestion)

    def _approve_suggestion(
        self,
        *,
        profile: BusinessProfile,
        suggestion: BusinessProfileSuggestion,
        approved_fact: dict[str, object],
        resolution_status: str,
        resolved_at: datetime,
        actor_id: str,
    ) -> tuple[BusinessProfile, BusinessProfileSuggestion]:
        approved_facts = dict(profile.approved_facts or {})
        provenance = dict(profile.provenance or {})
        category = suggestion.suggested_category

        approved_facts[category] = approved_fact
        provenance[category] = {
            "actor_id": actor_id,
            "suggestion_id": str(suggestion.id),
            "resolved_at": resolved_at.isoformat(),
            "decision": resolution_status,
        }

        profile.approved_facts = approved_facts
        profile.provenance = provenance
        profile.updated_at = resolved_at

        suggestion.status = resolution_status
        suggestion.resolved_at = resolved_at
        suggestion.resolution = {
            "actor_id": actor_id,
            "decision": resolution_status,
            "approved_fact": approved_fact,
        }

        self._session.add(profile)
        self._session.add(suggestion)
        self._session.flush()
        self._session.refresh(profile)
        self._session.refresh(suggestion)
        return profile, suggestion

    def _update_suggestion(self, suggestion: BusinessProfileSuggestion) -> BusinessProfileSuggestion:
        self._session.add(suggestion)
        self._session.flush()
        self._session.refresh(suggestion)
        return suggestion
