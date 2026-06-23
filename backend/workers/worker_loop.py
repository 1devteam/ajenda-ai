"""Worker loop — claim, start, dispatch cycle.

The worker loop owns polling and claim/start orchestration. Real task execution,
heartbeats during execution, completion, failure, and output persistence are owned
by TaskDispatcher and WorkerRuntimeService.

This implementation:
- Dispatches real task execution via TaskDispatcher
- Maintains a liveness file at /tmp/worker-alive for K8s probes
- Uses structured logging (not print())
- Handles dispatcher failures with one fail-path compensation attempt
- Separates the poll loop from the execution loop cleanly
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from backend.db.tenant_session import activate_tenant_session
from backend.queue.base import QueueAdapter
from backend.runtime.claim_holders import worker_daemon_holder
from backend.services.worker_runtime_service import WorkerRuntimeService
from backend.workers.task_dispatcher import TaskDispatcher
from backend.workers.tenant_scheduler import FixedTenantClaimTarget, TenantClaimTarget

logger = logging.getLogger("ajenda.worker_loop")

_LIVENESS_FILE = Path("/tmp/worker-alive")
_LIVENESS_UPDATE_INTERVAL = 10.0  # seconds


@dataclass(slots=True)
class WorkerLoop:
    """Main worker execution loop.

    Polls the queue for tasks, claims them, starts execution, and delegates
    execution lifecycle authority to TaskDispatcher.
    """

    session_factory: sessionmaker  # type: ignore[type-arg]
    queue: QueueAdapter
    worker_id: str
    tenant_id: str | None = None
    claim_target: TenantClaimTarget | None = None
    poll_interval_seconds: float = 2.0
    heartbeat_interval_seconds: float = 15.0
    _last_liveness_update: float = field(default=0.0, init=False)
    _current_claim_tenant_id: str | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if self.claim_target is None:
            if self.tenant_id is None or not self.tenant_id.strip():
                raise ValueError("WorkerLoop requires tenant_id or claim_target")
            object.__setattr__(self, "claim_target", FixedTenantClaimTarget(tenant_id=self.tenant_id))

    def _execution_tenant_id(self) -> str | None:
        if self._current_claim_tenant_id is not None:
            return self._current_claim_tenant_id
        if isinstance(self.claim_target, FixedTenantClaimTarget):
            return self.claim_target.tenant_id
        return None

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
        assert self.claim_target is not None
        tenant_id = self.claim_target.next_tenant_id()
        if tenant_id is None:
            return None

        object.__setattr__(self, "_current_claim_tenant_id", tenant_id)
        session = self.session_factory()
        activate_tenant_session(session, tenant_id)
        lease_id: uuid.UUID | None = None
        started = False
        try:
            runtime = WorkerRuntimeService(session, self.queue)
            task = runtime.claim_next_task(
                tenant_id=tenant_id,
                worker_id=worker_daemon_holder(worker_id=self.worker_id),
            )
            if task is None:
                session.rollback()
                return None

            lease_id_str = task.metadata_json.get("worker_lease_id")
            if not isinstance(lease_id_str, str):
                raise ValueError("claimed task missing worker_lease_id in metadata")
            lease_id = uuid.UUID(lease_id_str)

            runtime.heartbeat(
                tenant_id=tenant_id,
                lease_id=lease_id,
                worker_id=self.worker_id,
            )
            runtime.start_execution(
                tenant_id=tenant_id,
                lease_id=lease_id,
                worker_id=self.worker_id,
            )
            started = True
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
            if lease_id is not None and not started:
                self._release_unstarted_claim_once(lease_id=lease_id, reason=str(exc))
            return None
        finally:
            session.close()

    def _release_unstarted_claim_once(self, *, lease_id: uuid.UUID, reason: str) -> None:
        tenant_id = self._execution_tenant_id()
        if tenant_id is None:
            return
        session = self.session_factory()
        try:
            activate_tenant_session(session, tenant_id)
            runtime = WorkerRuntimeService(session, self.queue)
            runtime.release(
                tenant_id=tenant_id,
                lease_id=lease_id,
                worker_id=self.worker_id,
            )
            session.commit()
            logger.warning(
                "worker_claim_start_released_queue_claim",
                extra={"lease_id": str(lease_id), "reason": reason},
            )
        except Exception as exc:
            session.rollback()
            logger.critical(
                "worker_claim_start_release_failed",
                extra={"lease_id": str(lease_id), "error": str(exc)},
            )
        finally:
            session.close()

    def _run_claimed_task(self, *, task_id: uuid.UUID, lease_id: uuid.UUID) -> None:
        """Dispatch real task execution and compensate if dispatcher raises."""
        tenant_id = self._execution_tenant_id()
        if tenant_id is None:
            raise RuntimeError("claimed task missing tenant context")
        try:
            dispatcher = TaskDispatcher(
                session_factory=self.session_factory,
                queue=self.queue,
                worker_id=self.worker_id,
                tenant_id=tenant_id,
            )
            dispatcher.execute(task_id=task_id, lease_id=lease_id)

        except Exception as exc:
            logger.error(
                "task_execution_failed",
                extra={"task_id": str(task_id), "error": str(exc)},
            )
            self._fail_once(lease_id=lease_id, reason=str(exc))

    def _fail_once(self, *, lease_id: uuid.UUID, reason: str) -> None:
        tenant_id = self._execution_tenant_id()
        if tenant_id is None:
            return
        session = self.session_factory()
        try:
            activate_tenant_session(session, tenant_id)
            runtime = WorkerRuntimeService(session, self.queue)
            runtime.fail(
                tenant_id=tenant_id,
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
