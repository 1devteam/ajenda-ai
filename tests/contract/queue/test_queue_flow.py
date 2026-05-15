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


def _message(tenant_id: str = "tenant-a") -> QueueMessage:
    return QueueMessage(
        tenant_id=tenant_id,
        task_id=uuid4(),
        mission_id=uuid4(),
        fleet_id=None,
        branch_id=None,
        payload={"kind": "contract"},
        enqueued_at=datetime.now(UTC),
    )


def test_complete_task_removes_claim_without_requeueing() -> None:
    adapter = LocalQueueAdapter()
    message = _message()
    assert adapter.enqueue_task(message).ok is True
    assert adapter.claim_task(tenant_id="tenant-a", worker_id="worker-1") == message

    result = adapter.complete_task(tenant_id="tenant-a", task_id=message.task_id, worker_id="worker-1")

    assert result.ok is True
    assert adapter.claim_task(tenant_id="tenant-a", worker_id="worker-2") is None


def test_fail_task_dead_letters_claim_without_requeueing() -> None:
    adapter = LocalQueueAdapter()
    message = _message()
    assert adapter.enqueue_task(message).ok is True
    assert adapter.claim_task(tenant_id="tenant-a", worker_id="worker-1") == message

    result = adapter.fail_task(tenant_id="tenant-a", task_id=message.task_id, worker_id="worker-1", reason="boom")

    assert result.ok is True
    assert adapter.claim_task(tenant_id="tenant-a", worker_id="worker-2") is None
    assert len(adapter._dead_letter) == 1
    envelope = adapter._dead_letter[0]
    assert envelope["task_id"] == str(message.task_id)
    assert envelope["worker_id"] == "worker-1"
    assert envelope["reason"] == "boom"
    assert envelope["payload"]["task_id"] == str(message.task_id)


def test_release_lease_requeues_claimed_work() -> None:
    adapter = LocalQueueAdapter()
    message = _message()
    assert adapter.enqueue_task(message).ok is True
    assert adapter.claim_task(tenant_id="tenant-a", worker_id="worker-1") == message

    result = adapter.release_lease(tenant_id="tenant-a", task_id=message.task_id, worker_id="worker-1")

    assert result.ok is True
    assert adapter.claim_task(tenant_id="tenant-a", worker_id="worker-2") == message


def test_move_to_dead_letter_removes_pending_work_and_records_retry_envelope() -> None:
    adapter = LocalQueueAdapter()
    message = _message()
    assert adapter.enqueue_task(message).ok is True

    result = adapter.move_to_dead_letter(tenant_id="tenant-a", task_id=message.task_id, reason="max retries")

    assert result.ok is True
    assert adapter.claim_task(tenant_id="tenant-a", worker_id="worker-1") is None
    assert adapter._dead_letter[0]["reason"] == "max retries"
    assert adapter._dead_letter[0]["payload"]["task_id"] == str(message.task_id)


def test_dead_letter_public_entry_uses_base_contract_fields() -> None:
    adapter = LocalQueueAdapter()
    message = _message()
    adapter.enqueue_task(message)

    result = adapter.move_to_dead_letter(tenant_id="tenant-a", task_id=message.task_id, reason="max retries")
    entries = adapter.list_dead_letter(tenant_id="tenant-a")

    assert result.ok is True
    assert len(entries) == 1
    entry = entries[0]
    assert entry.tenant_id == "tenant-a"
    assert entry.task_id == message.task_id
    assert entry.reason == "max retries"
    assert entry.error is None
    assert isinstance(entry.raw, dict)
    assert isinstance(entry.payload, dict)
    assert entry.payload["payload"]["tenant_id"] == "tenant-a"
