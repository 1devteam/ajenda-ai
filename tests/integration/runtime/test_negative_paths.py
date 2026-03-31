import pytest
from datetime import datetime, timezone
from uuid import uuid4

from backend.queue.base import QueueMessage
from backend.queue.local_adapter import LocalQueueAdapter


def test_duplicate_claim_is_blocked() -> None:
    adapter = LocalQueueAdapter()
    task_id = uuid4()
    adapter.enqueue_task(
        QueueMessage(
            tenant_id="tenant-a",
            task_id=task_id,
            mission_id=uuid4(),
            fleet_id=None,
            branch_id=None,
            payload={},
            enqueued_at=datetime.now(timezone.utc),
        )
    )
    first = adapter.claim_task(tenant_id="tenant-a", worker_id="worker-1")
    second = adapter.claim_task(tenant_id="tenant-a", worker_id="worker-2")
    assert first is not None
    assert second is None


def test_cross_tenant_claim_is_rejected_by_absence() -> None:
    adapter = LocalQueueAdapter()
    adapter.enqueue_task(
        QueueMessage(
            tenant_id="tenant-a",
            task_id=uuid4(),
            mission_id=uuid4(),
            fleet_id=None,
            branch_id=None,
            payload={},
            enqueued_at=datetime.now(timezone.utc),
        )
    )
    claimed = adapter.claim_task(tenant_id="tenant-b", worker_id="worker-1")
    assert claimed is None
