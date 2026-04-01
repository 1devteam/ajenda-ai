"""Task Dispatcher — real task execution engine.

This module replaces the time.sleep(45) placeholder in the original worker_loop.
It provides a structured execution framework where:
- Tasks are dispatched to handler functions based on task type
- Heartbeats are maintained during execution
- Failures are reported with full context
- The execution contract (complete/fail) is always honored

Handler registration:
    Register handlers via @TaskDispatcher.register_handler("task_type")
    Each handler receives (task, context) and returns a result dict.

Extension point:
    In Phase 2, replace the default_handler with real AI agent dispatch.
    The framework here is intentionally minimal — it enforces the contract
    without prescribing the execution model.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from backend.domain.execution_task import ExecutionTask
from backend.queue.base import QueueAdapter
from backend.services.worker_runtime_service import WorkerRuntimeService

logger = logging.getLogger("ajenda.task_dispatcher")

# Type alias for task handler functions
TaskHandler = Callable[[ExecutionTask, dict[str, Any]], dict[str, Any]]

_HANDLER_REGISTRY: dict[str, TaskHandler] = {}
_HEARTBEAT_INTERVAL = 15.0  # seconds


def register_handler(task_type: str) -> Callable[[TaskHandler], TaskHandler]:
    """Decorator to register a handler for a specific task type."""
    def decorator(fn: TaskHandler) -> TaskHandler:
        _HANDLER_REGISTRY[task_type] = fn
        logger.info("task_handler_registered", extra={"task_type": task_type})
        return fn
    return decorator


@dataclass(slots=True)
class TaskDispatcher:
    """Dispatches claimed tasks to registered handlers with heartbeat maintenance."""

    session_factory: sessionmaker  # type: ignore[type-arg]
    queue: QueueAdapter
    worker_id: str
    tenant_id: str

    def execute(self, *, task_id: uuid.UUID, lease_id: uuid.UUID) -> None:
        """Execute a claimed task. Always calls complete() or fail() — never returns silently."""
        task = self._load_task(task_id)
        if task is None:
            logger.error("dispatcher_task_not_found", extra={"task_id": str(task_id)})
            self._fail(lease_id=lease_id, reason="task not found at dispatch time")
            return

        task_type = task.metadata_json.get("task_type", "default")
        handler = _HANDLER_REGISTRY.get(task_type) or _HANDLER_REGISTRY.get("default")

        if handler is None:
            self._fail(
                lease_id=lease_id,
                reason=f"no handler registered for task_type='{task_type}'",
            )
            return

        # Start heartbeat thread
        stop_event = threading.Event()
        heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(lease_id, stop_event),
            daemon=True,
            name=f"heartbeat-{lease_id}",
        )
        heartbeat_thread.start()

        try:
            logger.info(
                "task_dispatch_start",
                extra={"task_id": str(task_id), "task_type": task_type},
            )
            context: dict[str, Any] = {
                "worker_id": self.worker_id,
                "tenant_id": self.tenant_id,
                "lease_id": str(lease_id),
            }
            result = handler(task, context)
            logger.info(
                "task_dispatch_complete",
                extra={"task_id": str(task_id), "result_keys": list(result.keys())},
            )
            self._complete(lease_id=lease_id)

        except Exception as exc:
            logger.error(
                "task_dispatch_handler_failed",
                extra={"task_id": str(task_id), "error": str(exc)},
            )
            self._fail(lease_id=lease_id, reason=str(exc))

        finally:
            stop_event.set()
            heartbeat_thread.join(timeout=5.0)

    def _heartbeat_loop(self, lease_id: uuid.UUID, stop: threading.Event) -> None:
        """Background thread: sends heartbeats every HEARTBEAT_INTERVAL seconds."""
        while not stop.wait(timeout=_HEARTBEAT_INTERVAL):
            session = self.session_factory()
            try:
                runtime = WorkerRuntimeService(session, self.queue)
                runtime.heartbeat(
                    tenant_id=self.tenant_id,
                    lease_id=lease_id,
                    worker_id=self.worker_id,
                )
                session.commit()
            except Exception as exc:
                session.rollback()
                logger.error(
                    "dispatcher_heartbeat_failed",
                    extra={"lease_id": str(lease_id), "error": str(exc)},
                )
            finally:
                session.close()

    def _complete(self, *, lease_id: uuid.UUID) -> None:
        session = self.session_factory()
        try:
            runtime = WorkerRuntimeService(session, self.queue)
            runtime.complete(
                tenant_id=self.tenant_id,
                lease_id=lease_id,
                worker_id=self.worker_id,
            )
            session.commit()
        except Exception as exc:
            session.rollback()
            logger.error(
                "dispatcher_complete_failed",
                extra={"lease_id": str(lease_id), "error": str(exc)},
            )
        finally:
            session.close()

    def _fail(self, *, lease_id: uuid.UUID, reason: str) -> None:
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
        except Exception as exc:
            session.rollback()
            logger.critical(
                "dispatcher_fail_path_failed",
                extra={"lease_id": str(lease_id), "error": str(exc)},
            )
        finally:
            session.close()

    def _load_task(self, task_id: uuid.UUID) -> ExecutionTask | None:
        session = self.session_factory()
        try:
            from backend.repositories.execution_task_repository import ExecutionTaskRepository
            repo = ExecutionTaskRepository(session)
            return repo.get(task_id)
        except Exception as exc:
            logger.error("dispatcher_load_task_failed", extra={"error": str(exc)})
            return None
        finally:
            session.close()


# Default handler — logs and completes the task.
# Replace this in Phase 2 with real AI agent dispatch.
@register_handler("default")
def default_handler(task: ExecutionTask, context: dict[str, Any]) -> dict[str, Any]:
    """Default task handler. Logs task metadata and marks complete.

    This is the extension point for Phase 2 AI agent dispatch.
    Replace this handler with real execution logic.
    """
    logger.info(
        "default_handler_executing",
        extra={
            "task_id": str(task.id),
            "tenant_id": task.tenant_id,
            "metadata_keys": list(task.metadata_json.keys()),
        },
    )
    # Phase 2: dispatch to AI agent here
    return {"status": "completed", "handler": "default"}
