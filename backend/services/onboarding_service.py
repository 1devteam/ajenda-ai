from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from backend.domain.tenant_member import TenantMember
from backend.repositories.business_profile_repository import BusinessProfileRepository
from backend.repositories.tenant_onboarding_repository import TenantOnboardingRepository


@dataclass(frozen=True, slots=True)
class OnboardingSnapshot:
    setup_version: int
    completed: bool
    completed_at: str | None
    completed_by_member_id: str | None
    suppress_prompt: bool
    prompt_suppressed_at: str | None
    company_profile_ready: bool
    operating_preferences_ready: bool
    can_manage_connections: bool
    human_member: bool
    connections: dict[str, bool]


class OnboardingService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = TenantOnboardingRepository(session)

    def read(self, *, tenant_id: uuid.UUID, principal: Any) -> OnboardingSnapshot:
        facts = self._profile_facts(tenant_id)
        legacy_completed = bool(
            self._fact_text(facts.get("business_name"))
            and self._fact_text(facts.get("contact_email"))
            and "operating_charter" in facts
        )
        state = self._repo.get_or_create_state(tenant_id=tenant_id, legacy_completed=legacy_completed)
        member = self._member(tenant_id=tenant_id, principal=principal)
        preference = self._repo.get_preference(tenant_id=tenant_id, member_id=member.id) if member is not None else None
        return OnboardingSnapshot(
            setup_version=state.setup_version,
            completed=state.completed,
            completed_at=state.completed_at.isoformat() if state.completed_at else None,
            completed_by_member_id=str(state.completed_by_member_id) if state.completed_by_member_id else None,
            suppress_prompt=bool(preference and preference.suppress_setup_prompt),
            prompt_suppressed_at=(
                preference.suppressed_at.isoformat() if preference and preference.suppressed_at else None
            ),
            company_profile_ready=bool(
                self._fact_text(facts.get("business_name")) and self._fact_text(facts.get("contact_email"))
            ),
            operating_preferences_ready="operating_charter" in facts,
            can_manage_connections=bool(
                getattr(principal, "permissions", ())
                and "credentials:manage" in {str(p) for p in principal.permissions}
            ),
            human_member=member is not None,
            connections=self._connections(tenant_id),
        )

    def set_prompt_suppressed(self, *, tenant_id: uuid.UUID, principal: Any, suppress: bool) -> OnboardingSnapshot:
        member = self._require_member(tenant_id=tenant_id, principal=principal)
        self._repo.set_suppressed(tenant_id=tenant_id, member_id=member.id, suppress=suppress)
        self._session.flush()
        return self.read(tenant_id=tenant_id, principal=principal)

    def complete(self, *, tenant_id: uuid.UUID, principal: Any) -> OnboardingSnapshot:
        member = self._require_member(tenant_id=tenant_id, principal=principal)
        facts = self._profile_facts(tenant_id)
        if not self._fact_text(facts.get("business_name")) or not self._fact_text(facts.get("contact_email")):
            raise ValueError("business name and contact email are required before setup can be completed")
        if "operating_charter" not in facts:
            raise ValueError("operating preferences must be saved before setup can be completed")
        state = self._repo.get_or_create_state(tenant_id=tenant_id)
        now = datetime.now(UTC)
        state.completed_at = state.completed_at or now
        state.completed_by_member_id = state.completed_by_member_id or member.id
        state.updated_at = now
        self._session.flush()
        return self.read(tenant_id=tenant_id, principal=principal)

    def _member(self, *, tenant_id: uuid.UUID, principal: Any) -> TenantMember | None:
        return self._repo.member_for_subject(tenant_id=tenant_id, subject_id=str(getattr(principal, "subject_id", "")))

    def _require_member(self, *, tenant_id: uuid.UUID, principal: Any) -> TenantMember:
        member = self._member(tenant_id=tenant_id, principal=principal)
        if member is None:
            raise ValueError("onboarding changes require a human tenant member")
        return member

    def _profile_facts(self, tenant_id: uuid.UUID) -> dict[str, Any]:
        profile = BusinessProfileRepository(self._session).get_active_profile_for_tenant(tenant_id=str(tenant_id))
        return dict(profile.approved_facts or {}) if profile is not None else {}

    @staticmethod
    def _fact_text(value: Any) -> str:
        if isinstance(value, dict):
            value = value.get("value")
        return str(value or "").strip()

    def _connections(self, tenant_id: uuid.UUID) -> dict[str, bool]:
        from backend.repositories.provider_runtime_credential_repository import ProviderRuntimeCredentialRepository

        result = {"gmail": False, "google_calendar": False, "google_contacts": False, "google_docs": False}
        for credential in ProviderRuntimeCredentialRepository(self._session).list_for_tenant(tenant_id=str(tenant_id)):
            integration = str(credential.integration or "generic")
            if (
                integration in result
                and credential.enabled
                and not credential.revoked
                and credential.credential_type != "platform_master"
            ):
                result[integration] = True
        return result
