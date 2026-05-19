from datetime import UTC, datetime
from uuid import uuid4

from backend.queue.base import QueueMessage
from backend.queue.local_adapter import LocalQueueAdapter


def test_queue_enqueue_and_claim_flow() -> None:
    adapter = LocalQueueAdapter()
    message = QueueMessage(
        tenant_id="tenant-a",
        task_id=uuid4(),
        mission_id=uuid4(),
        fleet_id=None,
        branch_id=None,
        payload={},
        enqueued_at=datetime.now(UTC),
    )
    assert adapter.enqueue_task(message).ok is True
    claimed = adapter.claim_task(tenant_id="tenant-a", worker_id="worker-1")
    assert claimed is not None
    assert claimed.task_id == message.task_id
