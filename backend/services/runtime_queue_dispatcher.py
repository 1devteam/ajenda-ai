from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker

from backend.db.tenant_session import activate_tenant_session
from backend.domain.execution_task import ExecutionTask
from backend.domain.runtime_queue_dispatch import RuntimeQueueDispatch
from backend.queue.base import QueueAdapter, QueueMessage
from backend.repositories.runtime_queue_dispatch_repository import RuntimeQueueDispatchRepository

logger = logging.getLogger("ajenda.runtime_queue_dispatcher")

_AFTER_COMMIT_DISPATCHES = "runtime_queue_dispatches_after_commit"


@dataclass(frozen=True, slots=True)
class DispatchIntent:
    dispatch_id: uuid.UUID
    tenant_id: str
    message: QueueMessage
    queue: QueueAdapter


@dataclass(frozen=True, slots=True)
class DispatchPublishSummary:
    published_count: int = 0
    retry_scheduled_count: int = 0
    cancelled_cleanup_count: int = 0
    cancelled_cleanup_failed_count: int = 0


def queue_dispatch_after_commit(session: Session, intent: DispatchIntent) -> None:
    pending: list[DispatchIntent] = session.info.setdefault(_AFTER_COMMIT_DISPATCHES, [])
    if all(existing.dispatch_id != intent.dispatch_id for existing in pending):
        pending.append(intent)


@event.listens_for(Session, "after_rollback")
def _discard_uncommitted_dispatches(session: Session) -> None:
    # SAVEPOINT rollback is per-task isolation for mission admission. The
    # outer transaction still owns intents created by earlier successful
    # savepoints, so only an outer rollback may discard the intent set.
    if session.in_nested_transaction():
        return
    session.info.pop(_AFTER_COMMIT_DISPATCHES, None)


@event.listens_for(Session, "after_commit")
def _publish_committed_dispatches(session: Session) -> None:
    # ``after_commit`` also fires when a SQLAlchemy SAVEPOINT is released.
    # Publishing there would expose work before the owning PostgreSQL
    # transaction is durable.
    if session.in_nested_transaction():
        return
    intents: list[DispatchIntent] = session.info.pop(_AFTER_COMMIT_DISPATCHES, [])
    if not intents:
        return
    bind = session.get_bind()
    if bind is None:
        return
    factory = sessionmaker(bind=bind, autoflush=False, autocommit=False, expire_on_commit=False, future=True)
    for intent in intents:
        fresh = factory()
        try:
            activate_tenant_session(fresh, intent.tenant_id)
            dispatch = fresh.get(RuntimeQueueDispatch, intent.dispatch_id)
            if dispatch is None or dispatch.tenant_id != intent.tenant_id or dispatch.status != "pending":
                fresh.rollback()
                continue
            result = intent.queue.enqueue_task_idempotent(
                intent.message,
                idempotency_key=str(intent.dispatch_id),
            )
            dispatch.attempt_count += 1
            if result.ok:
                dispatch.status = "published"
                dispatch.published_at = datetime.now(UTC)
                dispatch.last_error = None
            else:
                dispatch.last_error = result.reason or "queue publication failed"
                dispatch.next_attempt_at = datetime.now(UTC) + RuntimeQueueDispatchService._backoff(
                    dispatch.attempt_count
                )
                logger.warning(
                    "runtime_queue_after_commit_publish_failed",
                    extra={"dispatch_id": str(intent.dispatch_id), "reason": result.reason},
                )
            fresh.commit()
        except Exception:
            fresh.rollback()
            logger.exception(
                "runtime_queue_after_commit_ack_failed",
                extra={"dispatch_id": str(intent.dispatch_id)},
            )
        finally:
            fresh.close()


class RuntimeQueueDispatchService:
    """Creates durable admission intents and reconciles them with the queue."""

    def __init__(self, session: Session, queue: QueueAdapter) -> None:
        self._session = session
        self._queue = queue
        self._dispatches = RuntimeQueueDispatchRepository(session)

    def admit(self, *, task: ExecutionTask, held_for_review: bool) -> tuple[RuntimeQueueDispatch, bool]:
        existing = self._dispatches.get_for_task(tenant_id=task.tenant_id, task_id=task.id)
        if existing is not None:
            if not held_for_review and existing.status == "held_review":
                return self.release_review_hold(task=task), False
            return existing, False
        now = datetime.now(UTC)
        dispatch = self._dispatches.add(
            RuntimeQueueDispatch(
                tenant_id=task.tenant_id,
                task_id=task.id,
                mission_id=task.mission_id,
                fleet_id=task.fleet_id,
                branch_id=task.branch_id,
                payload_json=dict(task.metadata_json or {}),
                status="held_review" if held_for_review else "pending",
                next_attempt_at=now,
            )
        )
        if not held_for_review:
            self._schedule_after_commit(dispatch)
        return dispatch, True

    def release_review_hold(self, *, task: ExecutionTask) -> RuntimeQueueDispatch:
        dispatch = self._dispatches.get_for_task(tenant_id=task.tenant_id, task_id=task.id)
        if dispatch is None or dispatch.status != "held_review":
            raise ValueError("reviewed task has no held runtime queue admission")
        dispatch.status = "pending"
        dispatch.payload_json = dict(task.metadata_json or {})
        dispatch.next_attempt_at = datetime.now(UTC)
        dispatch.last_error = None
        self._session.flush()
        self._schedule_after_commit(dispatch)
        return dispatch

    def cancel(self, *, task: ExecutionTask) -> RuntimeQueueDispatch | None:
        dispatch = self._dispatches.get_for_task(tenant_id=task.tenant_id, task_id=task.id)
        if dispatch is None or dispatch.status == "cancelled":
            return dispatch
        dispatch.status = "cancelled"
        dispatch.last_error = None
        dispatch.next_attempt_at = datetime.now(UTC)
        if dispatch.published_at is None:
            dispatch.cancelled_at = datetime.now(UTC)
        self._session.flush()
        return dispatch

    def publish_due(self, *, limit: int = 25) -> DispatchPublishSummary:
        now = datetime.now(UTC)
        published = retried = 0
        for dispatch in self._dispatches.list_due_pending(now=now, limit=limit):
            task = self._session.get(ExecutionTask, dispatch.task_id)
            if task is None or task.tenant_id != dispatch.tenant_id or task.status != "queued":
                dispatch.status = "cancelled"
                dispatch.cancelled_at = now if dispatch.published_at is None else None
                dispatch.last_error = "dispatch task is missing, cross-tenant, or no longer queued"
                self._session.commit()
                continue
            result = self._queue.enqueue_task_idempotent(
                self._message(dispatch),
                idempotency_key=str(dispatch.id),
            )
            dispatch.attempt_count += 1
            if result.ok:
                dispatch.status = "published"
                dispatch.published_at = now
                dispatch.last_error = None
                published += 1
            else:
                dispatch.last_error = result.reason or "queue publication failed"
                dispatch.next_attempt_at = now + self._backoff(dispatch.attempt_count)
                retried += 1
            self._session.commit()
        cleanup, cleanup_failed = self.reconcile_cancelled(limit=limit)
        return DispatchPublishSummary(published, retried, cleanup, cleanup_failed)

    def reconcile_cancelled(self, *, limit: int = 25) -> tuple[int, int]:
        cleaned = failed = 0
        now = datetime.now(UTC)
        for dispatch in self._dispatches.list_cancelled_for_cleanup(now=now, limit=limit):
            result = self._queue.cancel_task(tenant_id=dispatch.tenant_id, task_id=dispatch.task_id)
            if result.ok:
                dispatch.cancelled_at = datetime.now(UTC)
                dispatch.last_error = None
                cleaned += 1
            else:
                dispatch.attempt_count += 1
                dispatch.last_error = result.reason or "cancelled queue cleanup failed"
                dispatch.next_attempt_at = now + self._backoff(dispatch.attempt_count)
                failed += 1
            self._session.commit()
        return cleaned, failed

    def _schedule_after_commit(self, dispatch: RuntimeQueueDispatch) -> None:
        queue_dispatch_after_commit(
            self._session,
            DispatchIntent(
                dispatch_id=dispatch.id,
                tenant_id=dispatch.tenant_id,
                message=self._message(dispatch),
                queue=self._queue,
            ),
        )

    @staticmethod
    def _message(dispatch: RuntimeQueueDispatch) -> QueueMessage:
        return QueueMessage(
            tenant_id=dispatch.tenant_id,
            task_id=dispatch.task_id,
            mission_id=dispatch.mission_id,
            fleet_id=dispatch.fleet_id,
            branch_id=dispatch.branch_id,
            payload=dict(dispatch.payload_json or {}),
            enqueued_at=dispatch.created_at if dispatch.created_at is not None else datetime.now(UTC),
        )

    @staticmethod
    def _backoff(attempt_count: int) -> timedelta:
        return timedelta(seconds=min(300, 2 ** min(max(attempt_count, 1), 8)))
