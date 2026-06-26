from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from backend.app.config import Settings
from backend.queue.base import QueueMessage
from backend.queue.local_adapter import LocalQueueAdapter
from backend.workers.tenant_scheduler import (
    FixedTenantClaimTarget,
    RoundRobinActiveTenantClaimTarget,
    build_claim_target,
)


def test_fixed_claim_target_returns_configured_tenant() -> None:
    target = FixedTenantClaimTarget(tenant_id="tenant-a")
    assert target.next_tenant_id() == "tenant-a"


def test_round_robin_cycles_active_tenants() -> None:
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    session = MagicMock()
    repo = MagicMock()
    repo.list_active_tenant_ids.return_value = [tenant_a, tenant_b]

    target = RoundRobinActiveTenantClaimTarget(
        session_factory=lambda: session,
        refresh_interval_seconds=60.0,
    )

    with patch("backend.workers.tenant_scheduler.TenantRepository", return_value=repo):
        seen = [target.next_tenant_id(), target.next_tenant_id(), target.next_tenant_id()]

    assert seen == [tenant_a, tenant_b, tenant_a]


def test_build_claim_target_single_mode_uses_worker_tenant_id() -> None:
    settings = Settings.model_construct(
        worker_tenant_mode="single",
        worker_tenant_id="tenant-single",
        worker_tenant_refresh_seconds=30.0,
    )
    target = build_claim_target(settings, session_factory=MagicMock())
    assert isinstance(target, FixedTenantClaimTarget)
    assert target.next_tenant_id() == "tenant-single"


def test_build_claim_target_multi_mode_uses_round_robin() -> None:
    settings = Settings.model_construct(
        worker_tenant_mode="multi",
        worker_tenant_id="ignored",
        worker_tenant_refresh_seconds=15.0,
    )
    queue = LocalQueueAdapter()
    target = build_claim_target(settings, session_factory=MagicMock(), queue=queue)
    assert isinstance(target, RoundRobinActiveTenantClaimTarget)
    assert target.refresh_interval_seconds == 15.0
    assert target.queue is queue


def test_round_robin_sticky_tenant_drains_queue_before_rotating() -> None:
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    session = MagicMock()
    repo = MagicMock()
    repo.list_active_tenant_ids.return_value = [tenant_a, tenant_b]

    target = RoundRobinActiveTenantClaimTarget(
        session_factory=lambda: session,
        refresh_interval_seconds=60.0,
    )

    with patch("backend.workers.tenant_scheduler.TenantRepository", return_value=repo):
        first = target.next_tenant_id()
        target.record_claim_result(tenant_id=first, claimed=True)
        assert target.next_tenant_id() == first
        target.record_claim_result(tenant_id=first, claimed=False)
        second = target.next_tenant_id()
        assert second != first


def test_round_robin_prioritizes_tenants_with_pending_queue_depth() -> None:
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    tenant_c = str(uuid.uuid4())
    session = MagicMock()
    repo = MagicMock()
    repo.list_active_tenant_ids.return_value = [tenant_a, tenant_b, tenant_c]
    queue = LocalQueueAdapter()

    def enqueue_for(tenant_id: str) -> None:
        queue.enqueue_task(
            QueueMessage(
                tenant_id=tenant_id,
                task_id=uuid.uuid4(),
                mission_id=uuid.uuid4(),
                fleet_id=None,
                branch_id=None,
                payload={},
                enqueued_at=datetime.now(UTC),
            )
        )

    enqueue_for(tenant_c)

    target = RoundRobinActiveTenantClaimTarget(
        session_factory=lambda: session,
        refresh_interval_seconds=60.0,
        queue=queue,
    )

    with patch("backend.workers.tenant_scheduler.TenantRepository", return_value=repo):
        assert target.next_tenant_id() == tenant_c
        assert target.next_tenant_id() == tenant_c
