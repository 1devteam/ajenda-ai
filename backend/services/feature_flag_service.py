"""FeatureFlagService — runtime evaluation of tenant feature flags.

Thin primitive over TenantPlan.features_enabled (and future overrides).
Used for gating abilities, webhooks, compliance layers, canaries, etc.

All checks are tenant-scoped and fail-closed on invalid/suspended tenants.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from backend.repositories.tenant_repository import (
    TenantDeletedError,
    TenantNotFoundError,
    TenantRepository,
    TenantSuspendedError,
)


class FeatureFlagService:
    """Evaluates feature flags for a tenant at runtime.

    Backed by the tenant's current plan. Designed to be injectable and
    lightweight. Supports per-tenant overrides in a future iteration without
    changing call sites.
    """

    def __init__(self, session: Session, *, tenants: TenantRepository | None = None) -> None:
        self._tenants = tenants or TenantRepository(session)

    def is_enabled(self, tenant_id: uuid.UUID, feature: str) -> bool:
        """Return True if the feature is enabled for the (active) tenant.

        Unknown plans fail open (consistent with historical QuotaEnforcement behavior).
        """
        try:
            tenant = self._tenants.get_active(tenant_id)
        except (TenantNotFoundError, TenantSuspendedError, TenantDeletedError):
            return False

        plan = self._tenants.get_plan(tenant.plan)
        if plan is None:
            return True  # fail open
        return plan.allows_feature(feature)
