from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.member_onboarding_preference import MemberOnboardingPreference
from backend.domain.tenant_member import TenantMember
from backend.domain.tenant_onboarding_state import TenantOnboardingState


class TenantOnboardingRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_or_create_state(self, *, tenant_id: uuid.UUID, legacy_completed: bool = False) -> TenantOnboardingState:
        state = self._session.get(TenantOnboardingState, tenant_id)
        if state is None:
            state = TenantOnboardingState(
                tenant_id=tenant_id,
                setup_version=1,
                completed_at=datetime.now(UTC) if legacy_completed else None,
            )
            self._session.add(state)
            self._session.flush()
        return state

    def get_preference(self, *, tenant_id: uuid.UUID, member_id: uuid.UUID) -> MemberOnboardingPreference | None:
        return self._session.get(MemberOnboardingPreference, (tenant_id, member_id))

    def set_suppressed(
        self, *, tenant_id: uuid.UUID, member_id: uuid.UUID, suppress: bool
    ) -> MemberOnboardingPreference:
        preference = self.get_preference(tenant_id=tenant_id, member_id=member_id)
        now = datetime.now(UTC)
        if preference is None:
            preference = MemberOnboardingPreference(
                tenant_id=tenant_id,
                member_id=member_id,
                suppress_setup_prompt=suppress,
                suppressed_at=now if suppress else None,
            )
            self._session.add(preference)
        else:
            preference.suppress_setup_prompt = suppress
            preference.suppressed_at = now if suppress else None
            preference.updated_at = now
        self._session.flush()
        return preference

    def member_for_subject(self, *, tenant_id: uuid.UUID, subject_id: str) -> TenantMember | None:
        if not subject_id.startswith("user:"):
            return None
        try:
            member_id = uuid.UUID(subject_id.removeprefix("user:"))
        except ValueError:
            return None
        stmt = select(TenantMember).where(
            TenantMember.id == member_id,
            TenantMember.tenant_id == tenant_id,
            TenantMember.status == "active",
        )
        return self._session.scalar(stmt)
