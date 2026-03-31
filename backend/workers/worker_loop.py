from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import sessionmaker

from backend.domain.enums import ExecutionTaskState
from backend.queue.base import QueueAdapter
from backend.services.worker_runtime_service import WorkerRuntimeService


@dataclass(slots=True)
class WorkerLoop:
    session_factory: sessionmaker
    queue: QueueAdapter
    worker_id: str
    tenant_id: str
    poll_interval_seconds: float = 2.0
    heartbeat_interval_seconds: float = 15.0
    task_run_duration_seconds: float = 45.0

    def run_forever(self) -> None:
        while True:
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
            task = runtime.claim_next_task(tenant_id=self.tenant_id, worker_id=self.worker_id)
            if task is None:
                session.rollback()
                return None

            lease_id_str = task.metadata_json.get("worker_lease_id")
            if not isinstance(lease_id_str, str):
                raise ValueError("claimed task missing worker_lease_id")

            lease_id = uuid.UUID(lease_id_str)
            runtime.heartbeat(tenant_id=self.tenant_id, lease_id=lease_id, worker_id=self.worker_id)
            runtime.start_execution(tenant_id=self.tenant_id, lease_id=lease_id, worker_id=self.worker_id)
            session.commit()
            return task.id, lease_id
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            print(f"worker claim/start failed: {exc}", flush=True)
            return None
        finally:
            session.close()

    def _run_claimed_task(self, *, task_id: uuid.UUID, lease_id: uuid.UUID) -> None:
        started_at = time.monotonic()
        last_heartbeat_at = 0.0

        while True:
            now = time.monotonic()

            if now - last_heartbeat_at >= self.heartbeat_interval_seconds:
                if not self._heartbeat_once(lease_id=lease_id):
                    return
                last_heartbeat_at = now

            if now - started_at >= self.task_run_duration_seconds:
                self._complete_once(lease_id=lease_id)
                return

            if not self._task_is_still_running(task_id=task_id):
                return

            time.sleep(min(self.heartbeat_interval_seconds / 2.0, 1.0))

    def _heartbeat_once(self, *, lease_id: uuid.UUID) -> bool:
        session = self.session_factory()
        try:
            runtime = WorkerRuntimeService(session, self.queue)
            runtime.heartbeat(tenant_id=self.tenant_id, lease_id=lease_id, worker_id=self.worker_id)
            session.commit()
            return True
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            print(f"worker heartbeat failed for lease {lease_id}: {exc}", flush=True)
            self._fail_once(lease_id=lease_id, reason=f"heartbeat failure: {exc}")
            return False
        finally:
            session.close()

    def _complete_once(self, *, lease_id: uuid.UUID) -> None:
        session = self.session_factory()
        try:
            runtime = WorkerRuntimeService(session, self.queue)
            runtime.complete(tenant_id=self.tenant_id, lease_id=lease_id, worker_id=self.worker_id)
            session.commit()
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            print(f"worker completion failed for lease {lease_id}: {exc}", flush=True)
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
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            print(f"worker fail path failed for lease {lease_id}: {exc}", flush=True)
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
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            print(f"worker task state check failed for task {task_id}: {exc}", flush=True)
            return False
        finally:
            session.close()
