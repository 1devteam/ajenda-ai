from datetime import UTC, datetime
from uuid import uuid4

from backend.queue.base import QueueMessage
from backend.queue.local_adapter import LocalQueueAdapter


def test_worker_adapter_heartbeat_and_release() -> None:
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
            enqueued_at=datetime.now(UTC),
        )
    )
    adapter.claim_task(tenant_id="tenant-a", worker_id="worker-1")
    assert adapter.heartbeat(tenant_id="tenant-a", task_id=task_id, worker_id="worker-1").ok is True
    assert adapter.release_lease(tenant_id="tenant-a", task_id=task_id, worker_id="worker-1").ok is True
