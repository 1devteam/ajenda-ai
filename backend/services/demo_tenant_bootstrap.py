from __future__ import annotations

from sqlalchemy.orm import Session

from backend.repositories.business_profile_repository import BusinessProfileRepository
from backend.repositories.tenant_internal_record_repository import TenantInternalRecordRepository
from backend.services.ajenda_demo_fixtures import seed_ajenda_live_demo


class DemoTenantBootstrapService:
    """Own optional Ajenda demo materialization outside the repository layer."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._records = TenantInternalRecordRepository(session)
        self._profiles = BusinessProfileRepository(session)

    def ensure_seeded_if_empty(self, *, tenant_id: str) -> bool:
        """Seed only a tenant with neither durable records nor approved profile truth."""

        if self._records.has_active_records(tenant_id=tenant_id):
            return False
        profile = self._profiles.get_active_profile_for_tenant(tenant_id=tenant_id)
        if profile is not None and isinstance(profile.approved_facts, dict) and profile.approved_facts:
            return False
        seed_ajenda_live_demo(session=self._session, tenant_id=tenant_id)
        return True
