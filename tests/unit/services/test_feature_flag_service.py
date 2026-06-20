"""Basic contract tests for FeatureFlagService (PR2)."""

import uuid
from unittest.mock import MagicMock

from backend.services.feature_flag_service import FeatureFlagService


def _make_tenant(plan: str = "free", status: str = "active"):
    t = MagicMock()
    t.plan = plan
    t.status = status
    t.id = uuid.uuid4()
    return t


def _make_plan(features: list[str] | None = None):
    p = MagicMock()
    p.allows_feature = lambda f: f in (features or [])
    return p


def test_is_enabled_uses_plan_features():
    tenant = _make_tenant("pro")
    plan = _make_plan(["webhooks", "ability_runtime"])

    db = MagicMock()
    flags = FeatureFlagService(db)
    flags._tenants = MagicMock()
    flags._tenants.get_active.return_value = tenant
    flags._tenants.get_plan.return_value = plan

    assert flags.is_enabled(tenant.id, "webhooks") is True
    assert flags.is_enabled(tenant.id, "ability_runtime") is True
    assert flags.is_enabled(tenant.id, "compliance_layer") is False


def test_is_enabled_fails_closed_for_unknown_tenant():
    from backend.repositories.tenant_repository import TenantNotFoundError

    flags = FeatureFlagService(MagicMock())
    flags._tenants = MagicMock()
    flags._tenants.get_active.side_effect = TenantNotFoundError("x")
    assert flags.is_enabled(uuid.uuid4(), "anything") is False


def test_is_enabled_fails_closed_for_suspended():
    from backend.repositories.tenant_repository import TenantSuspendedError

    tenant = _make_tenant("pro", status="suspended")

    db = MagicMock()
    flags = FeatureFlagService(db)
    flags._tenants = MagicMock()
    flags._tenants.get_active.side_effect = TenantSuspendedError("suspended")
    assert flags.is_enabled(tenant.id, "webhooks") is False
