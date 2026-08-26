from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from backend.queue.base import QueueMessage

pytestmark = pytest.mark.integration


def _message(tenant_id: str = "tenant-owner-integrity") -> QueueMessage:
    return QueueMessage(
        tenant_id=tenant_id,
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        fleet_id=None,
        branch_id=None,
        payload={"owner_integrity": True},
        enqueued_at=datetime.now(UTC),
    )


def _claim(queue_adapter, *, worker_id: str = "worker-a") -> QueueMessage:
    message = _message()
    assert queue_adapter.enqueue_task(message).ok is True
    claimed = queue_adapter.claim_task(tenant_id=message.tenant_id, worker_id=worker_id)
    assert claimed is not None
    assert claimed.task_id == message.task_id
    return claimed


def _lease_key(message: QueueMessage) -> str:
    return f"ajenda:queue:{message.tenant_id}:lease:{message.task_id}"


def _processing_key(message: QueueMessage) -> str:
    return f"ajenda:queue:{message.tenant_id}:processing"


def _pending_key(message: QueueMessage) -> str:
    return f"ajenda:queue:{message.tenant_id}:pending"


def _dead_letter_key(message: QueueMessage) -> str:
    return f"ajenda:queue:{message.tenant_id}:dead_letter"


def test_foreign_worker_cannot_heartbeat_or_replace_owner(queue_adapter, redis_client) -> None:
    claimed = _claim(queue_adapter)
    assert redis_client.get(_lease_key(claimed)) == "worker-a"

    denied = queue_adapter.heartbeat(
        tenant_id=claimed.tenant_id,
        task_id=claimed.task_id,
        worker_id="worker-b",
    )
    assert denied.ok is False
    assert denied.reason == "worker does not own claim"
    assert redis_client.get(_lease_key(claimed)) == "worker-a"

    renewed = queue_adapter.heartbeat(
        tenant_id=claimed.tenant_id,
        task_id=claimed.task_id,
        worker_id="worker-a",
    )
    assert renewed.ok is True
    assert redis_client.get(_lease_key(claimed)) == "worker-a"


def test_foreign_worker_cannot_complete_claim(queue_adapter, redis_client) -> None:
    claimed = _claim(queue_adapter)

    denied = queue_adapter.complete_task(
        tenant_id=claimed.tenant_id,
        task_id=claimed.task_id,
        worker_id="worker-b",
    )
    assert denied.ok is False
    assert denied.reason == "worker does not own claim"
    assert redis_client.llen(_processing_key(claimed)) == 1
    assert redis_client.get(_lease_key(claimed)) == "worker-a"

    completed = queue_adapter.complete_task(
        tenant_id=claimed.tenant_id,
        task_id=claimed.task_id,
        worker_id="worker-a",
    )
    assert completed.ok is True
    assert redis_client.llen(_processing_key(claimed)) == 0
    assert redis_client.get(_lease_key(claimed)) is None


def test_foreign_worker_cannot_fail_claim(queue_adapter, redis_client) -> None:
    claimed = _claim(queue_adapter)

    denied = queue_adapter.fail_task(
        tenant_id=claimed.tenant_id,
        task_id=claimed.task_id,
        worker_id="worker-b",
        reason="foreign failure",
    )
    assert denied.ok is False
    assert denied.reason == "worker does not own claim"
    assert redis_client.llen(_processing_key(claimed)) == 1
    assert redis_client.llen(_dead_letter_key(claimed)) == 0
    assert redis_client.get(_lease_key(claimed)) == "worker-a"

    failed = queue_adapter.fail_task(
        tenant_id=claimed.tenant_id,
        task_id=claimed.task_id,
        worker_id="worker-a",
        reason="owner failure",
    )
    assert failed.ok is True
    assert redis_client.llen(_processing_key(claimed)) == 0
    assert redis_client.llen(_dead_letter_key(claimed)) == 1
    assert redis_client.get(_lease_key(claimed)) is None


def test_foreign_worker_cannot_release_claim(queue_adapter, redis_client) -> None:
    claimed = _claim(queue_adapter)

    denied = queue_adapter.release_lease(
        tenant_id=claimed.tenant_id,
        task_id=claimed.task_id,
        worker_id="worker-b",
    )
    assert denied.ok is False
    assert denied.reason == "worker does not own claim"
    assert redis_client.llen(_processing_key(claimed)) == 1
    assert redis_client.llen(_pending_key(claimed)) == 0
    assert redis_client.get(_lease_key(claimed)) == "worker-a"

    released = queue_adapter.release_lease(
        tenant_id=claimed.tenant_id,
        task_id=claimed.task_id,
        worker_id="worker-a",
    )
    assert released.ok is True
    assert redis_client.llen(_processing_key(claimed)) == 0
    assert redis_client.llen(_pending_key(claimed)) == 1
    assert redis_client.get(_lease_key(claimed)) is None


def test_recovery_accepts_recorded_owner_and_rejects_different_owner(queue_adapter, redis_client) -> None:
    claimed = _claim(queue_adapter)

    denied = queue_adapter.recover_task_for_retry(
        tenant_id=claimed.tenant_id,
        task_id=claimed.task_id,
        worker_id="worker-b",
    )
    assert denied.ok is False
    assert denied.reason == "worker does not own claim"
    assert redis_client.llen(_processing_key(claimed)) == 1
    assert redis_client.get(_lease_key(claimed)) == "worker-a"

    recovered = queue_adapter.recover_task_for_retry(
        tenant_id=claimed.tenant_id,
        task_id=claimed.task_id,
        worker_id="worker-a",
    )
    assert recovered.ok is True
    assert redis_client.llen(_processing_key(claimed)) == 0
    assert redis_client.llen(_pending_key(claimed)) == 1
    assert redis_client.get(_lease_key(claimed)) is None


def test_ownerless_recovery_can_reconcile_abandoned_processing_payload(queue_adapter, redis_client) -> None:
    claimed = _claim(queue_adapter)
    redis_client.delete(_lease_key(claimed))

    recovered = queue_adapter.recover_task_for_retry(
        tenant_id=claimed.tenant_id,
        task_id=claimed.task_id,
        worker_id="runtime_maintainer",
    )
    assert recovered.ok is True
    assert redis_client.llen(_processing_key(claimed)) == 0
    assert redis_client.llen(_pending_key(claimed)) == 1


def test_ownerless_dead_letter_path_cannot_steal_live_claim(queue_adapter, redis_client) -> None:
    claimed = _claim(queue_adapter)

    denied = queue_adapter.move_to_dead_letter(
        tenant_id=claimed.tenant_id,
        task_id=claimed.task_id,
        reason="administrative cleanup",
    )
    assert denied.ok is False
    assert denied.reason == "active worker owns claim"
    assert redis_client.llen(_processing_key(claimed)) == 1
    assert redis_client.llen(_dead_letter_key(claimed)) == 0

    redis_client.delete(_lease_key(claimed))
    moved = queue_adapter.move_to_dead_letter(
        tenant_id=claimed.tenant_id,
        task_id=claimed.task_id,
        reason="abandoned cleanup",
    )
    assert moved.ok is True
    assert redis_client.llen(_processing_key(claimed)) == 0
    assert redis_client.llen(_dead_letter_key(claimed)) == 1


def test_existing_claim_cannot_overwrite_foreign_lease_owner(queue_adapter, redis_client) -> None:
    message = _message()
    assert queue_adapter.enqueue_task(message).ok is True
    redis_client.set(_lease_key(message), "worker-a", ex=90)

    denied = queue_adapter.claim_existing_task(
        tenant_id=message.tenant_id,
        task_id=message.task_id,
        worker_id="worker-b",
    )
    assert denied.ok is False
    assert denied.reason == "task already claimed by different worker"
    assert redis_client.get(_lease_key(message)) == "worker-a"
    assert redis_client.llen(_pending_key(message)) == 1
    assert redis_client.llen(_processing_key(message)) == 0


def test_new_claim_does_not_overwrite_foreign_lease_owner(queue_adapter, redis_client) -> None:
    message = _message()
    assert queue_adapter.enqueue_task(message).ok is True
    redis_client.set(_lease_key(message), "worker-a", ex=90)

    with pytest.raises(RuntimeError, match="task already claimed by different worker"):
        queue_adapter.claim_task(tenant_id=message.tenant_id, worker_id="worker-b")

    assert redis_client.get(_lease_key(message)) == "worker-a"
    assert redis_client.llen(_pending_key(message)) == 1
    assert redis_client.llen(_processing_key(message)) == 0
