from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from backend.queue.base import QueueMessage
from backend.queue.local_adapter import LocalQueueAdapter


def _message(tenant_id: str = "tenant-a") -> QueueMessage:
    return QueueMessage(
        tenant_id=tenant_id,
        task_id=uuid4(),
        mission_id=uuid4(),
        fleet_id=None,
        branch_id=None,
        payload={"kind": "unit"},
        enqueued_at=datetime.now(UTC),
    )


def test_pending_depth_counts_only_matching_tenant_pending_messages() -> None:
    adapter = LocalQueueAdapter()
    tenant_a_message = _message("tenant-a")
    tenant_b_message = _message("tenant-b")
    assert adapter.enqueue_task(tenant_a_message).ok is True
    assert adapter.enqueue_task(tenant_a_message).ok is True
    assert adapter.enqueue_task(tenant_b_message).ok is True

    assert adapter.pending_depth(tenant_id="tenant-a") == 2
    assert adapter.pending_depth(tenant_id="tenant-b") == 1
    assert adapter.pending_depth(tenant_id="tenant-c") == 0


def test_complete_task_removes_claimed_message_and_lease_without_requeue() -> None:
    adapter = LocalQueueAdapter()
    message = _message()
    assert adapter.enqueue_task(message).ok is True
    assert adapter.claim_task(tenant_id="tenant-a", worker_id="worker-1") == message

    result = adapter.complete_task(tenant_id="tenant-a", task_id=message.task_id, worker_id="worker-1")

    assert result.ok is True
    assert adapter.claim_task(tenant_id="tenant-a", worker_id="worker-2") is None
    assert adapter.heartbeat(tenant_id="tenant-a", task_id=message.task_id, worker_id="worker-1").ok is False


def test_fail_task_removes_claimed_message_and_records_redis_compatible_dead_letter() -> None:
    adapter = LocalQueueAdapter()
    message = _message()
    assert adapter.enqueue_task(message).ok is True
    assert adapter.claim_task(tenant_id="tenant-a", worker_id="worker-1") == message

    result = adapter.fail_task(tenant_id="tenant-a", task_id=message.task_id, worker_id="worker-1", reason="boom")

    assert result.ok is True
    assert adapter.claim_task(tenant_id="tenant-a", worker_id="worker-2") is None
    assert adapter.heartbeat(tenant_id="tenant-a", task_id=message.task_id, worker_id="worker-1").ok is False
    assert len(adapter._dead_letter) == 1
    envelope = adapter._dead_letter[0]
    assert envelope["task_id"] == str(message.task_id)
    assert envelope["worker_id"] == "worker-1"
    assert envelope["reason"] == "boom"
    assert envelope["failed_at"]
    assert envelope["payload"]["task_id"] == str(message.task_id)
    assert envelope["payload"]["payload"] == {"kind": "unit"}


def test_release_lease_is_the_only_terminal_claim_method_that_requeues_work() -> None:
    adapter = LocalQueueAdapter()
    message = _message()
    assert adapter.enqueue_task(message).ok is True
    assert adapter.claim_task(tenant_id="tenant-a", worker_id="worker-1") == message

    result = adapter.release_lease(tenant_id="tenant-a", task_id=message.task_id, worker_id="worker-1")

    assert result.ok is True
    assert adapter.claim_task(tenant_id="tenant-a", worker_id="worker-2") == message


def test_move_to_dead_letter_removes_pending_work_and_preserves_retry_inspection() -> None:
    adapter = LocalQueueAdapter()
    message = _message()
    assert adapter.enqueue_task(message).ok is True

    result = adapter.move_to_dead_letter(tenant_id="tenant-a", task_id=message.task_id, reason="max retries")

    assert result.ok is True
    assert adapter.claim_task(tenant_id="tenant-a", worker_id="worker-1") is None
    assert len(adapter._dead_letter) == 1
    envelope = adapter._dead_letter[0]
    assert envelope["task_id"] == str(message.task_id)
    assert envelope["reason"] == "max retries"
    assert envelope["payload"]["task_id"] == str(message.task_id)


def test_list_processing_exposes_claimed_payload_for_recovery() -> None:
    adapter = LocalQueueAdapter()
    message = _message()
    assert adapter.enqueue_task(message).ok is True
    assert adapter.claim_task(tenant_id="tenant-a", worker_id="worker-1") == message

    rows = adapter.list_processing(tenant_id="tenant-a")

    assert len(rows) == 1
    assert rows[0].message == message
    assert rows[0].error is None


def test_retry_dead_letter_moves_one_entry_back_to_pending_once() -> None:
    adapter = LocalQueueAdapter()
    message = _message()
    assert adapter.enqueue_task(message).ok is True
    assert adapter.claim_task(tenant_id="tenant-a", worker_id="worker-1") == message
    assert adapter.fail_task(tenant_id="tenant-a", task_id=message.task_id, worker_id="worker-1", reason="boom").ok

    result = adapter.retry_dead_letter(tenant_id="tenant-a", task_id=message.task_id)

    assert result.ok is True
    assert adapter.claim_task(tenant_id="tenant-a", worker_id="worker-2") == message
    assert adapter.retry_dead_letter(tenant_id="tenant-a", task_id=message.task_id).ok is False
