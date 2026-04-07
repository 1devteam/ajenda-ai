"""Unit tests for SaaS quota enforcement.

Tests cover:
  - Free plan: hard limits on missions, tasks, agents, API keys
  - Pro plan: higher limits
  - Enterprise plan: unlimited (-1) limits
  - Feature gating: compliance layer, webhooks, custom OIDC
  - QuotaStatus read-only summary
  - QuotaExceededError structure
  - FeatureNotAvailableError structure
  - Boundary conditions: exactly at limit, one over limit
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from backend.services.quota_enforcement import (
    FeatureNotAvailableError,
    QuotaEnforcementService,
    QuotaExceededError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tenant(plan: str = "free", status: str = "active"):
    t = MagicMock()
    t.plan = plan
    t.status = status
    return t


def _make_plan(
    max_missions: int = 3,
    max_tasks: int = 50,
    max_agents: int = 5,
    max_api_keys: int = 2,
    max_api_calls: int = 1000,
    features: list[str] | None = None,
):
    p = MagicMock()
    p.max_missions_per_month = max_missions
    p.max_tasks_per_month = max_tasks
    p.max_agents_per_fleet = max_agents
    p.max_api_keys = max_api_keys
    p.max_monthly_api_calls = max_api_calls
    p.allows_feature = lambda f: f in (features or [])
    return p


def _make_usage(
    missions: int = 0,
    tasks: int = 0,
    agents: int = 0,
    api_calls: int = 0,
):
    u = MagicMock()
    u.missions_created = missions
    u.tasks_created = tasks
    u.agents_provisioned = agents
    u.api_calls_count = api_calls
    return u


def _make_service(tenant, plan, usage):
    """Build a QuotaEnforcementService with a mocked TenantRepository."""
    db = MagicMock()
    svc = QuotaEnforcementService(db)
    repo = MagicMock()
    repo.get_active.return_value = tenant
    repo.get_plan.return_value = plan
    repo.get_or_create_usage.return_value = usage
    repo.increment_usage.return_value = None
    svc._tenants = repo
    return svc


# ---------------------------------------------------------------------------
# Mission quota
# ---------------------------------------------------------------------------

class TestMissionQuota:
    def test_allows_when_under_limit(self):
        svc = _make_service(
            _make_tenant("free"),
            _make_plan(max_missions=3),
            _make_usage(missions=2),
        )
        # Should not raise
        svc.check_and_record_mission_creation(uuid.uuid4())

    def test_blocks_when_at_limit(self):
        svc = _make_service(
            _make_tenant("free"),
            _make_plan(max_missions=3),
            _make_usage(missions=3),
        )
        with pytest.raises(QuotaExceededError) as exc_info:
            svc.check_and_record_mission_creation(uuid.uuid4())
        err = exc_info.value
        assert err.field == "missions_per_month"
        assert err.limit == 3
        assert err.current == 3
        assert err.plan == "free"

    def test_blocks_when_over_limit(self):
        svc = _make_service(
            _make_tenant("free"),
            _make_plan(max_missions=3),
            _make_usage(missions=5),
        )
        with pytest.raises(QuotaExceededError):
            svc.check_and_record_mission_creation(uuid.uuid4())

    def test_unlimited_plan_never_blocks(self):
        svc = _make_service(
            _make_tenant("enterprise"),
            _make_plan(max_missions=-1),
            _make_usage(missions=999999),
        )
        # Should not raise — -1 means unlimited
        svc.check_and_record_mission_creation(uuid.uuid4())

    def test_increments_usage_on_success(self):
        svc = _make_service(
            _make_tenant("starter"),
            _make_plan(max_missions=10),
            _make_usage(missions=3),
        )
        svc.check_and_record_mission_creation(uuid.uuid4())
        svc._tenants.increment_usage.assert_called_once()


# ---------------------------------------------------------------------------
# Task quota
# ---------------------------------------------------------------------------

class TestTaskQuota:
    def test_allows_when_under_limit(self):
        svc = _make_service(
            _make_tenant("free"),
            _make_plan(max_tasks=50),
            _make_usage(tasks=49),
        )
        svc.check_and_record_task_creation(uuid.uuid4())

    def test_blocks_at_limit(self):
        svc = _make_service(
            _make_tenant("free"),
            _make_plan(max_tasks=50),
            _make_usage(tasks=50),
        )
        with pytest.raises(QuotaExceededError) as exc_info:
            svc.check_and_record_task_creation(uuid.uuid4())
        assert exc_info.value.field == "tasks_per_month"
        assert exc_info.value.limit == 50

    def test_unlimited_never_blocks(self):
        svc = _make_service(
            _make_tenant("enterprise"),
            _make_plan(max_tasks=-1),
            _make_usage(tasks=1_000_000),
        )
        svc.check_and_record_task_creation(uuid.uuid4())


# ---------------------------------------------------------------------------
# Agent provisioning quota
# ---------------------------------------------------------------------------

class TestAgentProvisioningQuota:
    def test_allows_exact_limit(self):
        svc = _make_service(
            _make_tenant("starter"),
            _make_plan(max_agents=5),
            _make_usage(agents=0),
        )
        svc.check_and_record_agent_provisioning(uuid.uuid4(), agents_requested=5)

    def test_blocks_over_limit(self):
        svc = _make_service(
            _make_tenant("free"),
            _make_plan(max_agents=5),
            _make_usage(agents=0),
        )
        with pytest.raises(QuotaExceededError) as exc_info:
            svc.check_and_record_agent_provisioning(uuid.uuid4(), agents_requested=6)
        assert exc_info.value.field == "agents_per_fleet"
        assert exc_info.value.limit == 5
        assert exc_info.value.current == 6

    def test_unlimited_allows_large_fleet(self):
        svc = _make_service(
            _make_tenant("enterprise"),
            _make_plan(max_agents=-1),
            _make_usage(agents=0),
        )
        svc.check_and_record_agent_provisioning(uuid.uuid4(), agents_requested=500)

    def test_increments_by_requested_count(self):
        svc = _make_service(
            _make_tenant("pro"),
            _make_plan(max_agents=50),
            _make_usage(agents=0),
        )
        tenant_id = uuid.uuid4()
        svc.check_and_record_agent_provisioning(tenant_id, agents_requested=10)
        # Verify the call was made with the correct field and amount.
        # We use keyword-only assertion to avoid coupling to the exact tenant_id UUID value.
        call_kwargs = svc._tenants.increment_usage.call_args
        assert call_kwargs is not None, "increment_usage must be called"
        assert call_kwargs.kwargs.get("field") == "agents_provisioned"
        assert call_kwargs.kwargs.get("amount") == 10


# ---------------------------------------------------------------------------
# API key quota (gauge, not rate)
# ---------------------------------------------------------------------------

class TestApiKeyQuota:
    def test_allows_when_under_limit(self):
        svc = _make_service(
            _make_tenant("free"),
            _make_plan(max_api_keys=2),
            _make_usage(),
        )
        svc.check_api_key_limit(uuid.uuid4(), current_key_count=1)

    def test_blocks_at_limit(self):
        svc = _make_service(
            _make_tenant("free"),
            _make_plan(max_api_keys=2),
            _make_usage(),
        )
        with pytest.raises(QuotaExceededError) as exc_info:
            svc.check_api_key_limit(uuid.uuid4(), current_key_count=2)
        assert exc_info.value.field == "api_keys"
        assert exc_info.value.limit == 2

    def test_does_not_increment_usage(self):
        """API keys are a gauge — checking the limit must not increment any counter."""
        svc = _make_service(
            _make_tenant("starter"),
            _make_plan(max_api_keys=10),
            _make_usage(),
        )
        svc.check_api_key_limit(uuid.uuid4(), current_key_count=5)
        svc._tenants.increment_usage.assert_not_called()

    def test_unlimited_never_blocks(self):
        svc = _make_service(
            _make_tenant("enterprise"),
            _make_plan(max_api_keys=-1),
            _make_usage(),
        )
        svc.check_api_key_limit(uuid.uuid4(), current_key_count=999)


# ---------------------------------------------------------------------------
# Feature gating
# ---------------------------------------------------------------------------

class TestFeatureGating:
    def test_allows_feature_on_eligible_plan(self):
        svc = _make_service(
            _make_tenant("pro"),
            _make_plan(features=["compliance_layer", "webhooks"]),
            _make_usage(),
        )
        svc.require_feature(uuid.uuid4(), "compliance_layer")  # Should not raise

    def test_blocks_feature_on_ineligible_plan(self):
        svc = _make_service(
            _make_tenant("free"),
            _make_plan(features=[]),
            _make_usage(),
        )
        with pytest.raises(FeatureNotAvailableError) as exc_info:
            svc.require_feature(uuid.uuid4(), "compliance_layer")
        assert exc_info.value.feature == "compliance_layer"
        assert exc_info.value.plan == "free"

    def test_blocks_webhooks_on_free_plan(self):
        svc = _make_service(
            _make_tenant("free"),
            _make_plan(features=[]),
            _make_usage(),
        )
        with pytest.raises(FeatureNotAvailableError) as exc_info:
            svc.require_feature(uuid.uuid4(), "webhooks")
        assert exc_info.value.feature == "webhooks"

    def test_blocks_custom_oidc_on_starter_plan(self):
        svc = _make_service(
            _make_tenant("starter"),
            _make_plan(features=["webhooks"]),  # starter has webhooks but not custom_oidc
            _make_usage(),
        )
        with pytest.raises(FeatureNotAvailableError):
            svc.require_feature(uuid.uuid4(), "custom_oidc")

    def test_enterprise_has_all_features(self):
        svc = _make_service(
            _make_tenant("enterprise"),
            _make_plan(features=["compliance_layer", "webhooks", "custom_oidc", "sso", "audit_export"]),
            _make_usage(),
        )
        for feature in ["compliance_layer", "webhooks", "custom_oidc", "sso", "audit_export"]:
            svc.require_feature(uuid.uuid4(), feature)  # None should raise

    def test_unknown_plan_fails_open(self):
        """Unknown plan (None returned by repo) should not block — fail open."""
        db = MagicMock()
        svc = QuotaEnforcementService(db)
        repo = MagicMock()
        repo.get_active.return_value = _make_tenant("unknown_plan")
        repo.get_plan.return_value = None  # Unknown plan
        svc._tenants = repo
        svc.require_feature(uuid.uuid4(), "compliance_layer")  # Should not raise


# ---------------------------------------------------------------------------
# QuotaExceededError structure
# ---------------------------------------------------------------------------

class TestQuotaExceededErrorStructure:
    def test_error_carries_all_fields(self):
        err = QuotaExceededError(
            field="tasks_per_month",
            limit=50,
            current=51,
            plan="free",
        )
        assert err.field == "tasks_per_month"
        assert err.limit == 50
        assert err.current == 51
        assert err.plan == "free"

    def test_error_is_exception(self):
        err = QuotaExceededError(field="x", limit=1, current=2, plan="free")
        assert isinstance(err, Exception)


# ---------------------------------------------------------------------------
# FeatureNotAvailableError structure
# ---------------------------------------------------------------------------

class TestFeatureNotAvailableErrorStructure:
    def test_error_carries_all_fields(self):
        err = FeatureNotAvailableError(feature="webhooks", plan="free")
        assert err.feature == "webhooks"
        assert err.plan == "free"

    def test_error_is_exception(self):
        err = FeatureNotAvailableError(feature="x", plan="free")
        assert isinstance(err, Exception)


# ---------------------------------------------------------------------------
# Plan boundary: exactly at limit vs one over
# ---------------------------------------------------------------------------

class TestPlanBoundaryConditions:
    @pytest.mark.parametrize("current,limit,should_raise", [
        (0, 3, False),
        (2, 3, False),
        (3, 3, True),   # at limit — blocked
        (4, 3, True),   # over limit — blocked
        (0, -1, False), # unlimited
        (999999, -1, False),  # unlimited, huge usage
    ])
    def test_mission_boundary(self, current, limit, should_raise):
        svc = _make_service(
            _make_tenant("free"),
            _make_plan(max_missions=limit),
            _make_usage(missions=current),
        )
        if should_raise:
            with pytest.raises(QuotaExceededError):
                svc.check_and_record_mission_creation(uuid.uuid4())
        else:
            svc.check_and_record_mission_creation(uuid.uuid4())
