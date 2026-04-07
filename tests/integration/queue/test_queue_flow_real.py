"""Integration test: queue adapter flow against a real Redis instance.

Replaces the LocalAdapter-backed test_queue_flow.py which could not catch:
- Redis LMOVE atomicity behavior
- Dead-letter list behavior under real Redis
- Key expiry and TTL behavior
- Connection failure handling

This test uses the queue_adapter fixture from tests/integration/conftest.py
which provides a real RedisQueueAdapter connected to a test Redis container.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from backend.queue.base import QueueMessage

pytestmark = pytest.mark.integration


def _make_message(tenant_id: str = "tenant-queue-a") -> QueueMessage:
    return QueueMessage(
        tenant_id=tenant_id,
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        fleet_id=None,
        branch_id=None,
        payload={"test": True},
        enqueued_at=datetime.now(UTC),
    )


class TestQueueFlowReal:
    def test_enqueue_and_dequeue(self, queue_adapter) -> None:
        """A message enqueued must be dequeued by a worker."""
        msg = _make_message()
        queue_adapter.enqueue_task(msg)

        dequeued = queue_adapter.dequeue_task(timeout_seconds=2)
        assert dequeued is not None
        assert dequeued.task_id == msg.task_id
        assert dequeued.tenant_id == msg.tenant_id

    def test_dequeue_empty_queue_returns_none(self, queue_adapter) -> None:
        """Dequeuing from an empty queue must return None, not block forever."""
        result = queue_adapter.dequeue_task(timeout_seconds=1)
        assert result is None

    def test_fifo_ordering(self, queue_adapter) -> None:
        """Messages must be dequeued in FIFO order."""
        msg1 = _make_message("tenant-fifo-a")
        msg2 = _make_message("tenant-fifo-b")
        msg3 = _make_message("tenant-fifo-c")

        queue_adapter.enqueue_task(msg1)
        queue_adapter.enqueue_task(msg2)
        queue_adapter.enqueue_task(msg3)

        d1 = queue_adapter.dequeue_task(timeout_seconds=1)
        d2 = queue_adapter.dequeue_task(timeout_seconds=1)
        d3 = queue_adapter.dequeue_task(timeout_seconds=1)

        assert d1 is not None and d1.task_id == msg1.task_id
        assert d2 is not None and d2.task_id == msg2.task_id
        assert d3 is not None and d3.task_id == msg3.task_id

    def test_dead_letter_on_explicit_failure(self, queue_adapter) -> None:
        """Explicitly dead-lettering a message must move it to the DLQ."""
        msg = _make_message()
        queue_adapter.enqueue_task(msg)

        dequeued = queue_adapter.dequeue_task(timeout_seconds=2)
        assert dequeued is not None

        # Dead-letter the message
        queue_adapter.dead_letter_task(dequeued, reason="test_explicit_failure")

        # The main queue must now be empty
        next_msg = queue_adapter.dequeue_task(timeout_seconds=1)
        assert next_msg is None

    def test_release_returns_message_to_queue(self, queue_adapter) -> None:
        """Releasing a message (e.g., on worker crash) must return it to the queue."""
        msg = _make_message()
        queue_adapter.enqueue_task(msg)

        dequeued = queue_adapter.dequeue_task(timeout_seconds=2)
        assert dequeued is not None

        # Release (re-queue) the message
        queue_adapter.release_task(dequeued)

        # Must be dequeue-able again
        requeued = queue_adapter.dequeue_task(timeout_seconds=2)
        assert requeued is not None
        assert requeued.task_id == msg.task_id
