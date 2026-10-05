from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.domain.business_profile import BusinessProfile, BusinessProfileSuggestion
from backend.services.business_profile_binding import (
    build_application_binding,
    ensure_proposal_binding,
    value_digest,
)


class BusinessProfileRepository:
    """Persistence contract for tenant-owned Business Profile records and suggestions."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_profile(self, profile: BusinessProfile) -> BusinessProfile:
        self._session.add(profile)
        self._session.flush()
        self._session.refresh(profile)
        return profile

    def get_or_create_active_profile(self, *, tenant_id: str) -> BusinessProfile:
        """Return the tenant active profile, creating it idempotently under races."""
        profile = self.get_active_profile_for_tenant(tenant_id=tenant_id)
        if profile is not None:
            return profile

        profile = BusinessProfile(tenant_id=tenant_id, approved_facts={}, provenance={})
        try:
            return self.add_profile(profile)
        except IntegrityError:
            self._session.rollback()
            existing = self.get_active_profile_for_tenant(tenant_id=tenant_id)
            if existing is None:
                raise
            return existing

    def get_profile_for_tenant(self, *, profile_id: uuid.UUID, tenant_id: str) -> BusinessProfile | None:
        stmt = select(BusinessProfile).where(BusinessProfile.id == profile_id, BusinessProfile.tenant_id == tenant_id)
        return self._session.scalar(stmt)

    def get_active_profile_for_tenant(self, *, tenant_id: str) -> BusinessProfile | None:
        stmt = select(BusinessProfile).where(
            BusinessProfile.tenant_id == tenant_id,
            BusinessProfile.status == "active",
        )
        return self._session.scalar(stmt)

    def upsert_approved_fact(
        self,
        *,
        profile: BusinessProfile,
        category: str,
        approved_fact: dict[str, object],
        actor_id: str,
        updated_at: datetime,
        provenance_metadata: dict[str, object] | None = None,
    ) -> BusinessProfile:
        if profile.status != "active":
            raise ValueError("only active business profiles can be updated")
        if not category.strip():
            raise ValueError("business profile fact category must be non-empty")

        approved_facts = dict(profile.approved_facts or {})
        provenance = dict(profile.provenance or {})
        previous_fact = approved_facts.get(category)
        previous_provenance = provenance.get(category)

        approved_facts[category] = approved_fact
        provenance_entry: dict[str, object] = {
            "actor_id": actor_id,
            "updated_at": updated_at.isoformat(),
            "decision": "direct_update",
        }
        if provenance_metadata:
            provenance_entry["metadata"] = provenance_metadata
        if previous_fact is not None:
            provenance_entry["superseded_fact"] = previous_fact
        if previous_provenance is not None:
            provenance_entry["superseded_provenance"] = previous_provenance
        provenance[category] = provenance_entry

        profile.approved_facts = approved_facts
        profile.provenance = provenance
        profile.updated_at = updated_at
        return self.update_profile(profile)

    def update_profile(self, profile: BusinessProfile) -> BusinessProfile:
        self._session.add(profile)
        self._session.flush()
        self._session.refresh(profile)
        return profile

    def add_suggestion(self, suggestion: BusinessProfileSuggestion) -> BusinessProfileSuggestion:
        ensure_proposal_binding(suggestion)
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

    def list_profile_history_for_tenant(self, *, tenant_id: str) -> dict[str, object]:
        """Build a tenant-scoped audit/history read model without mutating profile truth."""
        profile = self.get_active_profile_for_tenant(tenant_id=tenant_id)
        suggestions = self.list_suggestions_for_tenant(tenant_id=tenant_id)
        return {
            "profile": profile,
            "suggestions": suggestions,
        }

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
        self._require_pending_suggestion(suggestion)
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
        self._require_pending_suggestion(suggestion)
        suggestion.status = "dismissed"
        suggestion.resolved_at = resolved_at
        suggestion.resolution = {"actor_id": actor_id, "decision": "dismissed"}
        return self._update_suggestion(suggestion)

    def rollback_suggestion_review(
        self,
        *,
        suggestion: BusinessProfileSuggestion,
        rolled_back_at: datetime,
        actor_id: str,
    ) -> BusinessProfileSuggestion:
        if suggestion.status not in {"approved", "edited"}:
            raise ValueError("only applied business profile suggestions can be review-rolled back")
        suggestion.status = "review_rolled_back"
        suggestion.resolution = {
            **dict(suggestion.resolution or {}),
            "review_rollback": {"actor_id": actor_id, "at": rolled_back_at.isoformat()},
        }
        return self._update_suggestion(suggestion)

    def revert_suggestion_application(
        self,
        *,
        profile: BusinessProfile,
        suggestion: BusinessProfileSuggestion,
        reverted_at: datetime,
        actor_id: str,
    ) -> tuple[BusinessProfile, BusinessProfileSuggestion]:
        if suggestion.status not in {"approved", "edited", "review_rolled_back"}:
            raise ValueError("only applied business profile suggestions can be application-reverted")
        if profile.status != "active" or profile.tenant_id != suggestion.tenant_id:
            raise ValueError("business profile suggestion tenant does not match active profile")
        if suggestion.profile_id is not None and suggestion.profile_id != profile.id:
            raise ValueError("business profile suggestion does not belong to profile")

        resolution = dict(suggestion.resolution or {})
        binding = resolution.get("application_binding")
        if not isinstance(binding, dict) or not binding.get("application_digest"):
            raise ValueError("business profile application binding is unavailable")
        category = suggestion.suggested_category
        current_fact = (profile.approved_facts or {}).get(category)
        current_provenance = (profile.provenance or {}).get(category)
        if value_digest(current_fact) != binding.get("approved_fact_digest"):
            raise ValueError("business profile application changed after approval")
        current_binding = (
            current_provenance.get("application_binding") if isinstance(current_provenance, dict) else None
        )
        if not isinstance(current_binding, dict) or current_binding.get("application_digest") != binding.get(
            "application_digest"
        ):
            raise ValueError("business profile application provenance changed after approval")

        approved_facts = dict(profile.approved_facts or {})
        provenance = dict(profile.provenance or {})
        if "superseded_fact" in resolution:
            approved_facts[category] = resolution["superseded_fact"]
        else:
            approved_facts.pop(category, None)
        if "superseded_provenance" in resolution:
            provenance[category] = resolution["superseded_provenance"]
        else:
            provenance.pop(category, None)
        profile.approved_facts = approved_facts
        profile.provenance = provenance
        profile.updated_at = reverted_at
        suggestion.status = "application_reverted"
        suggestion.resolution = {
            **resolution,
            "application_reversion": {
                "actor_id": actor_id,
                "at": reverted_at.isoformat(),
                "restored_fact": approved_facts.get(category),
                "restored_provenance": provenance.get(category),
                "reverted_application_digest": binding["application_digest"],
            },
        }
        self._session.add(profile)
        self._session.add(suggestion)
        self._session.flush()
        self._session.refresh(profile)
        self._session.refresh(suggestion)
        return profile, suggestion

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
        self._require_pending_suggestion(suggestion)
        if profile.tenant_id != suggestion.tenant_id:
            raise ValueError("business profile suggestion tenant does not match profile tenant")
        if suggestion.profile_id is not None and suggestion.profile_id != profile.id:
            raise ValueError("business profile suggestion does not belong to profile")

        approved_facts = dict(profile.approved_facts or {})
        provenance = dict(profile.provenance or {})
        category = suggestion.suggested_category
        previous_fact = approved_facts.get(category)
        previous_provenance = provenance.get(category)
        application_binding = build_application_binding(
            suggestion=suggestion,
            profile=profile,
            approved_fact=approved_fact,
            previous_fact=previous_fact,
            previous_provenance=previous_provenance,
            decision=resolution_status,
        )

        approved_facts[category] = approved_fact
        provenance[category] = {
            "actor_id": actor_id,
            "suggestion_id": str(suggestion.id),
            "resolved_at": resolved_at.isoformat(),
            "decision": resolution_status,
            "application_binding": application_binding,
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
            "application_binding": application_binding,
        }
        if previous_fact is not None:
            suggestion.resolution["superseded_fact"] = previous_fact
        if previous_provenance is not None:
            suggestion.resolution["superseded_provenance"] = previous_provenance

        self._session.add(profile)
        self._session.add(suggestion)
        self._session.flush()
        self._session.refresh(profile)
        self._session.refresh(suggestion)
        return profile, suggestion

    def require_pending_suggestion(self, suggestion: BusinessProfileSuggestion) -> None:
        self._require_pending_suggestion(suggestion)

    def _require_pending_suggestion(self, suggestion: BusinessProfileSuggestion) -> None:
        if suggestion.status != "pending":
            raise ValueError("only pending business profile suggestions can be resolved")

    def _update_suggestion(self, suggestion: BusinessProfileSuggestion) -> BusinessProfileSuggestion:
        self._session.add(suggestion)
        self._session.flush()
        self._session.refresh(suggestion)
        return suggestion
