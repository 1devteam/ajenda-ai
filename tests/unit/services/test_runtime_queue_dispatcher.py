from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from backend.domain.enums import ExecutionTaskState
from backend.queue.base import QueueMessage, QueueOperationResult
from backend.queue.local_adapter import LocalQueueAdapter
from backend.services.runtime_queue_dispatcher import (
    _AFTER_COMMIT_DISPATCHES,
    DispatchIntent,
    RuntimeQueueDispatchService,
    queue_dispatch_after_commit,
)


def _intent(queue: LocalQueueAdapter) -> DispatchIntent:
    dispatch_id = uuid.uuid4()
    return DispatchIntent(
        dispatch_id=dispatch_id,
        tenant_id=str(uuid.uuid4()),
        message=QueueMessage(
            tenant_id=str(uuid.uuid4()),
            task_id=uuid.uuid4(),
            mission_id=uuid.uuid4(),
            fleet_id=None,
            branch_id=None,
            payload={},
            enqueued_at=datetime.now(UTC),
        ),
        queue=queue,
    )


def _dispatch(*, status: str = "pending") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=str(uuid.uuid4()),
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        fleet_id=None,
        branch_id=None,
        payload_json={"task_type": "echo"},
        status=status,
        attempt_count=0,
        next_attempt_at=datetime.now(UTC),
        last_error=None,
        published_at=None,
        cancelled_at=None,
        created_at=datetime.now(UTC),
    )


def test_nested_commit_does_not_publish_or_consume_outer_intent() -> None:
    queue = LocalQueueAdapter()
    intent = _intent(queue)
    session = Session(create_engine("sqlite://"))
    session.execute(text("SELECT 1"))
    queue_dispatch_after_commit(session, intent)

    with session.begin_nested():
        session.execute(text("SELECT 1"))

    assert session.info[_AFTER_COMMIT_DISPATCHES] == [intent]
    assert queue.claim_task(tenant_id=intent.tenant_id, worker_id="worker") is None

    session.rollback()
    assert _AFTER_COMMIT_DISPATCHES not in session.info


def test_nested_rollback_preserves_intents_from_prior_successful_savepoint() -> None:
    queue = LocalQueueAdapter()
    intent = _intent(queue)
    session = Session(create_engine("sqlite://"))
    session.execute(text("SELECT 1"))
    queue_dispatch_after_commit(session, intent)
    savepoint = session.begin_nested()

    savepoint.rollback()

    assert session.info[_AFTER_COMMIT_DISPATCHES] == [intent]
    session.rollback()


def test_publish_due_marks_success_and_local_queue_is_idempotent() -> None:
    session = MagicMock()
    queue = LocalQueueAdapter()
    service = RuntimeQueueDispatchService(session, queue)
    dispatch = _dispatch()
    task = SimpleNamespace(tenant_id=dispatch.tenant_id, status=ExecutionTaskState.QUEUED.value)
    service._dispatches = MagicMock()
    service._dispatches.list_due_pending.return_value = [dispatch]
    service._dispatches.list_cancelled_for_cleanup.return_value = []
    session.get.return_value = task

    first = service.publish_due()
    queue.enqueue_task_idempotent(service._message(dispatch), idempotency_key=str(dispatch.id))

    assert first.published_count == 1
    assert dispatch.status == "published"
    assert dispatch.attempt_count == 1
    claimed = queue.claim_task(tenant_id=dispatch.tenant_id, worker_id="worker")
    assert claimed is not None
    assert claimed.task_id == dispatch.task_id
    assert queue.claim_task(tenant_id=dispatch.tenant_id, worker_id="worker-2") is None


def test_retry_rearms_existing_dispatch_with_new_durable_delivery_generation() -> None:
    session = MagicMock()
    queue = LocalQueueAdapter()
    service = RuntimeQueueDispatchService(session, queue)
    dispatch = _dispatch(status="published")
    service._dispatches = MagicMock()
    service._dispatches.get_for_task.return_value = dispatch
    task = SimpleNamespace(
        id=dispatch.task_id,
        tenant_id=dispatch.tenant_id,
        metadata_json={"task_type": "echo"},
    )

    retried = service.retry(task=task)

    assert retried is dispatch
    assert dispatch.status == "pending"
    assert dispatch.published_at is None
    assert dispatch.payload_json["_runtime_queue_retry_generation"] == 1
    assert RuntimeQueueDispatchService._idempotency_key(dispatch).endswith(":retry:1")
    session.flush.assert_called_once_with()


def test_retry_publish_recovers_dead_letter_before_fallback_enqueue() -> None:
    queue = MagicMock()
    queue.retry_dead_letter.return_value = QueueOperationResult(ok=True)
    dispatch = _dispatch(status="pending")
    dispatch.payload_json = {"task_type": "echo", "_runtime_queue_retry_generation": 1}

    result = RuntimeQueueDispatchService._publish(dispatch=dispatch, queue=queue)

    assert result.ok is True
    queue.retry_dead_letter.assert_called_once_with(tenant_id=dispatch.tenant_id, task_id=dispatch.task_id)
    queue.enqueue_task_idempotent.assert_not_called()


def test_publish_due_records_retry_and_backoff_on_queue_outage() -> None:
    session = MagicMock()
    queue = MagicMock()
    queue.enqueue_task_idempotent.return_value = QueueOperationResult(ok=False, reason="redis unavailable")
    service = RuntimeQueueDispatchService(session, queue)
    dispatch = _dispatch()
    service._dispatches = MagicMock()
    service._dispatches.list_due_pending.return_value = [dispatch]
    service._dispatches.list_cancelled_for_cleanup.return_value = []
    session.get.return_value = SimpleNamespace(
        tenant_id=dispatch.tenant_id,
        status=ExecutionTaskState.QUEUED.value,
    )
    before = dispatch.next_attempt_at

    summary = service.publish_due()

    assert summary.retry_scheduled_count == 1
    assert dispatch.status == "pending"
    assert dispatch.attempt_count == 1
    assert dispatch.last_error == "redis unavailable"
    assert dispatch.next_attempt_at > before
    session.commit.assert_called_once_with()


def test_reconcile_cancelled_retains_repair_state_until_queue_cleanup_succeeds() -> None:
    session = MagicMock()
    queue = MagicMock()
    queue.cancel_task.side_effect = [
        QueueOperationResult(ok=False, reason="redis unavailable"),
        QueueOperationResult(ok=True),
    ]
    service = RuntimeQueueDispatchService(session, queue)
    dispatch = _dispatch(status="cancelled")
    dispatch.published_at = datetime.now(UTC)
    service._dispatches = MagicMock()
    service._dispatches.list_cancelled_for_cleanup.return_value = [dispatch]

    assert service.reconcile_cancelled() == (0, 1)
    assert dispatch.cancelled_at is None
    assert dispatch.last_error == "redis unavailable"

    assert service.reconcile_cancelled() == (1, 0)
    assert dispatch.cancelled_at is not None
    assert dispatch.last_error is None
