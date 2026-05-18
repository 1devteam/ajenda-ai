from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.domain.governance_event import GovernanceEvent
from backend.services.quota_enforcement import (
    FeatureNotAvailableError,
    QuotaEnforcementService,
    QuotaExceededError,
)
from backend.services.tenant_lifecycle import TenantLifecycleService


def _tenant(*, plan: str = "free", status: str = "active") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        slug="tenant-a",
        plan=plan,
        status=status,
    )


def _plan(**overrides: object) -> SimpleNamespace:
    values = {
        "max_missions_per_month": 5,
        "max_tasks_per_month": 10,
        "max_agents_per_fleet": 3,
        "max_api_keys": 2,
        "max_monthly_api_calls": 1_000,
        "allows_feature": lambda feature: feature == "webhooks",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _usage(**overrides: int) -> SimpleNamespace:
    values = {
        "missions_created": 0,
        "tasks_created": 0,
        "agents_provisioned": 0,
        "api_calls_count": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_tenant_lifecycle_provision_emits_governance_event() -> None:
    session = MagicMock()
    tenant = _tenant(plan="starter")
    repo = MagicMock()
    repo.get_by_slug.return_value = None
    repo.create.return_value = tenant

    with patch("backend.services.tenant_lifecycle.TenantRepository", return_value=repo):
        result = TenantLifecycleService(session).provision(
            name="Tenant A",
            slug="tenant-a",
            plan="starter",
            actor="admin-1",
        )

    assert result.tenant_id == tenant.id
    assert result.slug == "tenant-a"
    session.flush.assert_called_once()
    event = session.add.call_args.args[0]
    assert isinstance(event, GovernanceEvent)
    assert event.event_type == "tenant_provisioned"
    assert event.mission_id is None


def test_tenant_lifecycle_rejects_duplicate_slug() -> None:
    session = MagicMock()
    repo = MagicMock()
    repo.get_by_slug.return_value = _tenant()

    with patch("backend.services.tenant_lifecycle.TenantRepository", return_value=repo):
        with pytest.raises(ValueError, match="already exists"):
            TenantLifecycleService(session).provision(name="Tenant A", slug="tenant-a")


def test_tenant_lifecycle_suspend_requires_reason() -> None:
    service = TenantLifecycleService(MagicMock())

    with pytest.raises(ValueError, match="Suspension reason"):
        service.suspend(uuid.uuid4(), reason=" ", actor="admin-1")


def test_tenant_lifecycle_upgrade_plan_emits_old_and_new_plan() -> None:
    session = MagicMock()
    tenant_id = uuid.uuid4()
    tenant = _tenant(plan="free")
    repo = MagicMock()
    repo.get.return_value = tenant

    with patch("backend.services.tenant_lifecycle.TenantRepository", return_value=repo):
        TenantLifecycleService(session).upgrade_plan(
            tenant_id,
            new_plan="pro",
            actor="admin-1",
        )

    repo.update_plan.assert_called_once_with(tenant_id, new_plan="pro")
    event = session.add.call_args.args[0]
    assert event.event_type == "tenant_plan_changed"
    assert event.payload_json == {"old_plan": "free", "new_plan": "pro"}


def test_quota_records_mission_creation_when_under_limit() -> None:
    repo = MagicMock()
    tenant_id = uuid.uuid4()
    repo.get_active.return_value = _tenant(plan="free")
    repo.get_plan.return_value = _plan(max_missions_per_month=5)
    repo.get_or_create_usage.return_value = _usage(missions_created=4)

    with patch("backend.services.quota_enforcement.TenantRepository", return_value=repo):
        QuotaEnforcementService(MagicMock()).check_and_record_mission_creation(tenant_id)

    repo.increment_usage.assert_called_once_with(tenant_id, field="missions_created")


def test_quota_rejects_task_batch_that_would_exceed_limit() -> None:
    repo = MagicMock()
    tenant_id = uuid.uuid4()
    repo.get_active.return_value = _tenant(plan="free")
    repo.get_plan.return_value = _plan(max_tasks_per_month=10)
    repo.get_or_create_usage.return_value = _usage(tasks_created=9)

    with patch("backend.services.quota_enforcement.TenantRepository", return_value=repo):
        with pytest.raises(QuotaExceededError) as exc_info:
            QuotaEnforcementService(MagicMock()).check_and_record_task_creation(
                tenant_id,
                count=2,
            )

    assert exc_info.value.field == "tasks_per_month"
    repo.increment_usage.assert_not_called()


def test_quota_rejects_invalid_task_count() -> None:
    service = QuotaEnforcementService(MagicMock())

    with pytest.raises(ValueError, match="count must be >= 1"):
        service.check_and_record_task_creation(uuid.uuid4(), count=0)


def test_quota_allows_unlimited_plan() -> None:
    repo = MagicMock()
    tenant_id = uuid.uuid4()
    repo.get_active.return_value = _tenant(plan="enterprise")
    repo.get_plan.return_value = _plan(max_tasks_per_month=-1)
    repo.get_or_create_usage.return_value = _usage(tasks_created=999_999)

    with patch("backend.services.quota_enforcement.TenantRepository", return_value=repo):
        QuotaEnforcementService(MagicMock()).check_and_record_task_creation(
            tenant_id,
            count=100,
        )

    repo.increment_usage.assert_called_once_with(
        tenant_id,
        field="tasks_created",
        amount=100,
    )


def test_feature_gate_rejects_missing_feature() -> None:
    repo = MagicMock()
    tenant_id = uuid.uuid4()
    repo.get_active.return_value = _tenant(plan="free")
    repo.get_plan.return_value = _plan(allows_feature=lambda feature: False)

    with patch("backend.services.quota_enforcement.TenantRepository", return_value=repo):
        with pytest.raises(FeatureNotAvailableError):
            QuotaEnforcementService(MagicMock()).require_feature(tenant_id, "webhooks")


def test_quota_status_reports_usage_and_limits() -> None:
    repo = MagicMock()
    tenant_id = uuid.uuid4()
    repo.get_active.return_value = _tenant(plan="starter")
    repo.get_plan.return_value = _plan(max_tasks_per_month=500)
    repo.get_or_create_usage.return_value = _usage(tasks_created=12, api_calls_count=99)

    with patch("backend.services.quota_enforcement.TenantRepository", return_value=repo):
        status = QuotaEnforcementService(MagicMock()).get_quota_status(tenant_id)

    assert status.tenant_id == str(tenant_id)
    assert status.plan == "starter"
    assert status.tasks_created == 12
    assert status.tasks_limit == 500
    assert status.api_calls_count == 99
