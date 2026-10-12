from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest

from backend.queue.base import QueueMessage

pytestmark = pytest.mark.integration


def _message(tenant_id: str) -> QueueMessage:
    return QueueMessage(
        tenant_id=tenant_id,
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        fleet_id=None,
        branch_id=None,
        payload={"migration": True},
        enqueued_at=datetime.now(UTC),
    )


def _legacy_key(tenant_id: str, state: str) -> str:
    return f"ajenda:queue:{tenant_id}:{state}"


def _v2_key(tenant_id: str, state: str) -> str:
    return f"ajenda:queue:{tenant_id}:v2:{state}"


def test_legacy_lists_migrate_atomically_and_preserve_fifo(queue_adapter, redis_client) -> None:
    tenant_id = "tenant-migration"
    first = _message(tenant_id)
    second = _message(tenant_id)
    processing = _message(tenant_id)
    dead = _message(tenant_id)
    encode = queue_adapter._encode_message

    redis_client.rpush(_legacy_key(tenant_id, "pending"), encode(first), encode(second))
    redis_client.rpush(_legacy_key(tenant_id, "processing"), encode(processing))
    redis_client.lpush(
        _legacy_key(tenant_id, "dead_letter"),
        json.dumps(
            {
                "task_id": str(dead.task_id),
                "reason": "legacy failure",
                "payload": json.loads(encode(dead)),
            }
        ),
    )

    assert queue_adapter.pending_depth(tenant_id=tenant_id) == 2

    assert redis_client.get(_v2_key(tenant_id, "schema")) == "indexed-v2"
    assert redis_client.exists(_legacy_key(tenant_id, "pending")) == 0
    assert redis_client.exists(_legacy_key(tenant_id, "processing")) == 0
    assert redis_client.exists(_legacy_key(tenant_id, "dead_letter")) == 0
    assert redis_client.zrange(_v2_key(tenant_id, "pending-order"), 0, -1) == [
        str(first.task_id),
        str(second.task_id),
    ]
    assert redis_client.hexists(_v2_key(tenant_id, "processing-payloads"), str(processing.task_id))
    assert redis_client.zrange(_v2_key(tenant_id, "dead-letter-order"), 0, -1) == [str(dead.task_id)]

    claimed = queue_adapter.claim_task(tenant_id=tenant_id, worker_id="worker-a")
    assert claimed is not None
    assert claimed.task_id == first.task_id


def test_legacy_write_after_migration_fails_closed(queue_adapter, redis_client) -> None:
    tenant_id = "tenant-post-migration-write"
    first = _message(tenant_id)
    assert queue_adapter.enqueue_task(first).ok is True

    late = _message(tenant_id)
    redis_client.rpush(_legacy_key(tenant_id, "pending"), queue_adapter._encode_message(late))

    denied = queue_adapter.enqueue_task(_message(tenant_id))

    assert denied.ok is False
    assert "legacy queue received data after indexed migration" in (denied.reason or "")
    assert redis_client.llen(_legacy_key(tenant_id, "pending")) == 1
    assert redis_client.zcard(_v2_key(tenant_id, "pending-order")) == 1


def test_migration_rejects_cross_tenant_payload_without_partial_index(queue_adapter, redis_client) -> None:
    tenant_id = "tenant-migration-owner"
    foreign = _message("tenant-foreign")
    redis_client.rpush(_legacy_key(tenant_id, "pending"), queue_adapter._encode_message(foreign))

    denied = queue_adapter.enqueue_task(_message(tenant_id))

    assert denied.ok is False
    assert "legacy pending payload tenant mismatch" in (denied.reason or "")
    assert redis_client.llen(_legacy_key(tenant_id, "pending")) == 1
    assert redis_client.exists(_v2_key(tenant_id, "schema")) == 0
    assert redis_client.exists(_v2_key(tenant_id, "pending-order")) == 0


def test_migration_rejects_duplicate_live_task_without_partial_index(queue_adapter, redis_client) -> None:
    tenant_id = "tenant-migration-duplicate"
    message = _message(tenant_id)
    raw = queue_adapter._encode_message(message)
    redis_client.rpush(_legacy_key(tenant_id, "pending"), raw)
    redis_client.rpush(_legacy_key(tenant_id, "processing"), raw)

    denied = queue_adapter.enqueue_task(_message(tenant_id))

    assert denied.ok is False
    assert "duplicate live task" in (denied.reason or "")
    assert redis_client.llen(_legacy_key(tenant_id, "pending")) == 1
    assert redis_client.llen(_legacy_key(tenant_id, "processing")) == 1
    assert redis_client.exists(_v2_key(tenant_id, "schema")) == 0
