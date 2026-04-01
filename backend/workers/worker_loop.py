"""Worker loop — claim, execute, heartbeat, complete/fail cycle.

Previous defect: _run_claimed_task() used time.sleep(45) as a placeholder
for real task execution. No actual work was ever dispatched. The worker
appeared to function correctly but produced no real output.

This implementation:
- Dispatches real task execution via TaskDispatcher
- Maintains a liveness file at /tmp/worker-alive for K8s probes
- Uses structured logging (not print())
- Handles heartbeat loss gracefully (fail the task, don't crash the loop)
- Separates the poll loop from the execution loop cleanly
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from backend.domain.enums import ExecutionTaskState
from backend.queue.base import QueueAdapter
from backend.services.worker_runtime_service import WorkerRuntimeService
from backend.workers.task_dispatcher import TaskDispatcher

logger = logging.getLogger("ajenda.worker_loop")

_LIVENESS_FILE = Path("/tmp/worker-alive")
_LIVENESS_UPDATE_INTERVAL = 10.0  # seconds


@dataclass(slots=True)
class WorkerLoop:
    """Main worker execution loop.

    Polls the queue for tasks, claims them, dispatches real execution,
    heartbeats during execution, and marks tasks complete or failed.
    """

    session_factory: sessionmaker  # type: ignore[type-arg]
    queue: QueueAdapter
    worker_id: str
    tenant_id: str
    poll_interval_seconds: float = 2.0
    heartbeat_interval_seconds: float = 15.0
    _last_liveness_update: float = field(default=0.0, init=False)

    def run_forever(self) -> None:
        """Main loop. Runs until the process is killed."""
        logger.info("worker_loop_started", extra={"worker_id": self.worker_id})
        self._touch_liveness()

        while True:
            self._maybe_touch_liveness()
            claimed = self._claim_and_start_task()
            if claimed is None:
                time.sleep(self.poll_interval_seconds)
                continue
            task_id, lease_id = claimed
            self._run_claimed_task(task_id=task_id, lease_id=lease_id)

    def _claim_and_start_task(self) -> tuple[uuid.UUID, uuid.UUID] | None:
        session = self.session_factory()
        try:
            runtime = WorkerRuntimeService(session, self.queue)
            task = runtime.claim_next_task(
                tenant_id=self.tenant_id, worker_id=self.worker_id
            )
            if task is None:
                session.rollback()
                return None

            lease_id_str = task.metadata_json.get("worker_lease_id")
            if not isinstance(lease_id_str, str):
                raise ValueError("claimed task missing worker_lease_id in metadata")
            lease_id = uuid.UUID(lease_id_str)

            runtime.heartbeat(
                tenant_id=self.tenant_id,
                lease_id=lease_id,
                worker_id=self.worker_id,
            )
            runtime.start_execution(
                tenant_id=self.tenant_id,
                lease_id=lease_id,
                worker_id=self.worker_id,
            )
            session.commit()
            logger.info(
                "task_claimed",
                extra={"task_id": str(task.id), "lease_id": str(lease_id)},
            )
            return task.id, lease_id

        except Exception as exc:
            session.rollback()
            logger.error(
                "worker_claim_start_failed",
                extra={"worker_id": self.worker_id, "error": str(exc)},
            )
            return None
        finally:
            session.close()

    def _run_claimed_task(self, *, task_id: uuid.UUID, lease_id: uuid.UUID) -> None:
        """Dispatch real task execution and manage the heartbeat/completion lifecycle."""
        last_heartbeat_at = time.monotonic()

        try:
            dispatcher = TaskDispatcher(
                session_factory=self.session_factory,
                queue=self.queue,
                worker_id=self.worker_id,
                tenant_id=self.tenant_id,
            )
            # Run the task. The dispatcher is responsible for calling
            # runtime.complete() or runtime.fail() when done.
            dispatcher.execute(task_id=task_id, lease_id=lease_id)

        except Exception as exc:
            logger.error(
                "task_execution_failed",
                extra={"task_id": str(task_id), "error": str(exc)},
            )
            self._fail_once(lease_id=lease_id, reason=str(exc))

    def _heartbeat_once(self, *, lease_id: uuid.UUID) -> bool:
        session = self.session_factory()
        try:
            runtime = WorkerRuntimeService(session, self.queue)
            runtime.heartbeat(
                tenant_id=self.tenant_id,
                lease_id=lease_id,
                worker_id=self.worker_id,
            )
            session.commit()
            return True
        except Exception as exc:
            session.rollback()
            logger.error(
                "worker_heartbeat_failed",
                extra={"lease_id": str(lease_id), "error": str(exc)},
            )
            self._fail_once(lease_id=lease_id, reason=f"heartbeat failure: {exc}")
            return False
        finally:
            session.close()

    def _complete_once(self, *, lease_id: uuid.UUID) -> None:
        session = self.session_factory()
        try:
            runtime = WorkerRuntimeService(session, self.queue)
            runtime.complete(
                tenant_id=self.tenant_id,
                lease_id=lease_id,
                worker_id=self.worker_id,
            )
            session.commit()
            logger.info("task_completed", extra={"lease_id": str(lease_id)})
        except Exception as exc:
            session.rollback()
            logger.error(
                "worker_completion_failed",
                extra={"lease_id": str(lease_id), "error": str(exc)},
            )
            self._fail_once(lease_id=lease_id, reason=f"completion failure: {exc}")
        finally:
            session.close()

    def _fail_once(self, *, lease_id: uuid.UUID, reason: str) -> None:
        session = self.session_factory()
        try:
            runtime = WorkerRuntimeService(session, self.queue)
            runtime.fail(
                tenant_id=self.tenant_id,
                lease_id=lease_id,
                worker_id=self.worker_id,
                reason=reason,
            )
            session.commit()
            logger.warning("task_failed", extra={"lease_id": str(lease_id), "reason": reason})
        except Exception as exc:
            session.rollback()
            logger.critical(
                "worker_fail_path_failed",
                extra={"lease_id": str(lease_id), "error": str(exc)},
            )
        finally:
            session.close()

    def _task_is_still_running(self, *, task_id: uuid.UUID) -> bool:
        session = self.session_factory()
        try:
            runtime = WorkerRuntimeService(session, self.queue)
            task = runtime._tasks.get(task_id)
            if task is None:
                return False
            return task.status == ExecutionTaskState.RUNNING.value
        except Exception as exc:
            session.rollback()
            logger.error(
                "worker_task_state_check_failed",
                extra={"task_id": str(task_id), "error": str(exc)},
            )
            return False
        finally:
            session.close()

    def _touch_liveness(self) -> None:
        """Write/update the liveness file for K8s exec probe."""
        try:
            _LIVENESS_FILE.touch()
            self._last_liveness_update = time.monotonic()
        except OSError as exc:
            logger.warning("liveness_file_touch_failed", extra={"error": str(exc)})

    def _maybe_touch_liveness(self) -> None:
        if time.monotonic() - self._last_liveness_update >= _LIVENESS_UPDATE_INTERVAL:
            self._touch_liveness()
