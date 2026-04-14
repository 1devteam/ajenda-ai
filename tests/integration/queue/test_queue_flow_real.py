"""Integration test: queue adapter flow against a real Redis instance.

Validates the authoritative queue adapter contract against a real Redis
instance. This test covers enqueue, claim, release, dead-letter, and
tenant-scoped FIFO behaviour using the actual runtime API.
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
    def test_enqueue_and_claim(self, queue_adapter) -> None:
        msg = _make_message()
        result = queue_adapter.enqueue_task(msg)
        assert result.ok is True

        claimed = queue_adapter.claim_task(tenant_id=msg.tenant_id, worker_id="worker-1")
        assert claimed is not None
        assert claimed.task_id == msg.task_id
        assert claimed.tenant_id == msg.tenant_id

    def test_claim_empty_queue_returns_none(self, queue_adapter) -> None:
        result = queue_adapter.claim_task(tenant_id="tenant-empty", worker_id="worker-1")
        assert result is None

    def test_fifo_ordering_within_tenant(self, queue_adapter) -> None:
        tenant_id = "tenant-fifo-a"
        msg1 = _make_message(tenant_id)
        msg2 = _make_message(tenant_id)
        msg3 = _make_message(tenant_id)

        assert queue_adapter.enqueue_task(msg1).ok is True
        assert queue_adapter.enqueue_task(msg2).ok is True
        assert queue_adapter.enqueue_task(msg3).ok is True

        c1 = queue_adapter.claim_task(tenant_id=tenant_id, worker_id="worker-1")
        c2 = queue_adapter.claim_task(tenant_id=tenant_id, worker_id="worker-1")
        c3 = queue_adapter.claim_task(tenant_id=tenant_id, worker_id="worker-1")

        assert c1 is not None and c1.task_id == msg1.task_id
        assert c2 is not None and c2.task_id == msg2.task_id
        assert c3 is not None and c3.task_id == msg3.task_id

    def test_dead_letter_on_explicit_failure(self, queue_adapter) -> None:
        msg = _make_message()
        assert queue_adapter.enqueue_task(msg).ok is True

        claimed = queue_adapter.claim_task(tenant_id=msg.tenant_id, worker_id="worker-1")
        assert claimed is not None

        result = queue_adapter.move_to_dead_letter(
            tenant_id=claimed.tenant_id,
            task_id=claimed.task_id,
            reason="test_explicit_failure",
        )
        assert result.ok is True

        next_msg = queue_adapter.claim_task(tenant_id=msg.tenant_id, worker_id="worker-1")
        assert next_msg is None

    def test_release_returns_message_to_queue(self, queue_adapter) -> None:
        msg = _make_message()
        assert queue_adapter.enqueue_task(msg).ok is True

        claimed = queue_adapter.claim_task(tenant_id=msg.tenant_id, worker_id="worker-1")
        assert claimed is not None

        result = queue_adapter.release_lease(
            tenant_id=claimed.tenant_id,
            task_id=claimed.task_id,
            worker_id="worker-1",
        )
        assert result.ok is True

        requeued = queue_adapter.claim_task(tenant_id=msg.tenant_id, worker_id="worker-1")
        assert requeued is not None
        assert requeued.task_id == msg.task_id
