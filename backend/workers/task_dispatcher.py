"""Task Dispatcher — real task execution engine.

This module replaces the time.sleep(45) placeholder in the original worker_loop.
It provides a structured execution framework where:
- Tasks are dispatched to handler functions based on task type
- Heartbeats are maintained during execution
- Failures are reported with full context
- The execution contract (complete/fail) is always honored

Handler registration:
    Register handlers via @register_handler("task_type")
    Each handler receives (task, context) and returns a result dict.

Extension point:
    In Phase 2, replace the default_handler with real AI agent dispatch.
    The framework here is intentionally minimal — it enforces the contract
    without prescribing the execution model.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypedDict, cast

from sqlalchemy.orm import Session, sessionmaker

from backend.db.tenant_session import activate_tenant_session
from backend.domain.execution_task import ExecutionTask
from backend.queue.base import QueueAdapter
from backend.services.tools.schemas import SideEffectClass
from backend.services.worker_runtime_service import WorkerRuntimeService

logger = logging.getLogger("ajenda.task_dispatcher")


class TaskHandlerContext(TypedDict):
    """Runtime context passed into task handlers."""

    worker_id: str
    tenant_id: str
    lease_id: str
    session_factory: Any


TaskHandler = Callable[[ExecutionTask, TaskHandlerContext], dict[str, Any]]

_HANDLER_REGISTRY: dict[str, TaskHandler] = {}
_OUTPUT_REASON_BY_TASK_TYPE: dict[str, str] = {}
_HEARTBEAT_INTERVAL = 15.0  # seconds
_TOOL_INVOKE_TASK_TYPE = "tool.invoke"
_TOOL_INVOKE_HANDLER = "tool.invoke"
_COMPLETED_STATUS = "completed"


def register_handler(
    task_type: str,
    *,
    output_reason: str | None = None,
) -> Callable[[TaskHandler], TaskHandler]:
    """Decorator to register a handler for a specific task type."""

    normalized_task_type = _normalize_task_type(task_type)
    normalized_output_reason = _normalize_output_reason(output_reason)

    def decorator(fn: TaskHandler) -> TaskHandler:
        if normalized_task_type in _HANDLER_REGISTRY:
            raise ValueError(f"task handler already registered for task_type='{normalized_task_type}'")

        _HANDLER_REGISTRY[normalized_task_type] = fn
        if normalized_output_reason is not None:
            _OUTPUT_REASON_BY_TASK_TYPE[normalized_task_type] = normalized_output_reason

        logger.info("task_handler_registered", extra={"task_type": normalized_task_type})
        return fn

    return decorator


def _normalize_task_type(task_type: str) -> str:
    normalized_task_type = task_type.strip()
    if not normalized_task_type:
        raise ValueError("task_type must be a non-empty string")
    return normalized_task_type


def _normalize_output_reason(output_reason: str | None) -> str | None:
    if output_reason is None:
        return None
    normalized_output_reason = output_reason.strip()
    if not normalized_output_reason:
        raise ValueError("output_reason must be a non-empty string when provided")
    return normalized_output_reason


def _task_type_for_task(task: ExecutionTask) -> str:
    raw_task_type = task.metadata_json.get("task_type", "default")
    if raw_task_type is None:
        raw_task_type = "default"
    if not isinstance(raw_task_type, str):
        raise ValueError("task metadata task_type must be a string")
    return _normalize_task_type(raw_task_type)


def _side_effecting_tool_invoke_class(
    *,
    task_type: str,
    result: dict[str, Any],
) -> str | None:
    """Return side-effect class for completed tool.invoke output that cannot be replayed safely."""

    if task_type != _TOOL_INVOKE_TASK_TYPE:
        return None
    if result.get("handler") != _TOOL_INVOKE_HANDLER or result.get("status") != _COMPLETED_STATUS:
        return None

    raw_side_effect_class = result.get("side_effect_class")
    if not isinstance(raw_side_effect_class, str):
        return None

    try:
        side_effect_class = SideEffectClass(raw_side_effect_class.strip())
    except ValueError:
        return None

    if not side_effect_class.has_side_effect:
        return None
    return side_effect_class.value


def _validate_handler_result(
    result: object,
    *,
    require_json_serializable: bool = False,
) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise ValueError("task handler must return a result object")

    if not all(isinstance(key, str) for key in result):
        raise ValueError("task handler result keys must be strings")

    handler = result.get("handler")
    if not isinstance(handler, str) or not handler.strip():
        raise ValueError('task handler result must include non-empty "handler"')

    status = result.get("status")
    if not isinstance(status, str) or not status.strip():
        raise ValueError('task handler result must include non-empty "status"')

    if status != "completed":
        raise ValueError('task handler result status must be "completed"')

    if require_json_serializable:
        try:
            json.dumps(result)
        except (TypeError, ValueError) as exc:
            raise ValueError("task handler result must be JSON serializable") from exc

    return cast("dict[str, Any]", result)


@dataclass(slots=True)
class TaskDispatcher:
    """Dispatches claimed tasks to registered handlers with heartbeat maintenance."""

    session_factory: sessionmaker  # type: ignore[type-arg]
    queue: QueueAdapter
    worker_id: str
    tenant_id: str

    def _open_tenant_session(self) -> Session:
        session = cast(Session, self.session_factory())
        activate_tenant_session(session, self.tenant_id)
        return session

    def execute(self, *, task_id: uuid.UUID, lease_id: uuid.UUID) -> None:
        """Execute a claimed task. Always calls complete() or fail() — never returns silently."""
        task = self._load_task(task_id)
        if task is None:
            logger.error("dispatcher_task_not_found", extra={"task_id": str(task_id)})
            self._fail(lease_id=lease_id, reason="task not found at dispatch time")
            return

        try:
            task_type = _task_type_for_task(task)
        except ValueError as exc:
            self._fail(lease_id=lease_id, reason=str(exc))
            return

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
            context: TaskHandlerContext = {
                "worker_id": self.worker_id,
                "tenant_id": self.tenant_id,
                "lease_id": str(lease_id),
                "session_factory": self.session_factory,
            }
            output_reason = _OUTPUT_REASON_BY_TASK_TYPE.get(task_type)
            result = _validate_handler_result(
                handler(task, context),
                require_json_serializable=output_reason is not None,
            )

            logger.info(
                "task_dispatch_complete",
                extra={"task_id": str(task_id), "result_keys": list(result.keys())},
            )
            try:
                self._complete(
                    lease_id=lease_id,
                    task=task,
                    result=result if output_reason is not None else None,
                    output_reason=output_reason,
                )
            except Exception as exc:
                side_effect_class = _side_effecting_tool_invoke_class(task_type=task_type, result=result)
                if side_effect_class is None:
                    raise

                logger.critical(
                    "task_dispatch_completion_failed_after_side_effect",
                    extra={
                        "task_id": str(task_id),
                        "lease_id": str(lease_id),
                        "task_type": task_type,
                        "side_effect_class": side_effect_class,
                        "error": str(exc),
                    },
                )
                self._block_completion_failure(
                    lease_id=lease_id,
                    task_id=task_id,
                    task_type=task_type,
                    side_effect_class=side_effect_class,
                    reason=str(exc),
                )

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
            session = self._open_tenant_session()
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

    def _complete(
        self,
        *,
        lease_id: uuid.UUID,
        task: ExecutionTask,
        result: dict[str, Any] | None = None,
        output_reason: str | None = None,
    ) -> None:
        session = self._open_tenant_session()
        try:
            runtime = WorkerRuntimeService(session, self.queue)
            runtime.complete(
                tenant_id=self.tenant_id,
                lease_id=lease_id,
                worker_id=self.worker_id,
                task_output=result,
                output_reason=output_reason,
            )
        except Exception as exc:
            session.rollback()
            logger.error(
                "dispatcher_complete_failed",
                extra={"lease_id": str(lease_id), "error": str(exc)},
            )
            raise
        finally:
            session.close()

    def _block_completion_failure(
        self,
        *,
        lease_id: uuid.UUID,
        task_id: uuid.UUID,
        task_type: str,
        side_effect_class: str,
        reason: str,
    ) -> None:
        session = self._open_tenant_session()
        try:
            runtime = WorkerRuntimeService(session, self.queue)
            runtime.block_completion_failure(
                tenant_id=self.tenant_id,
                lease_id=lease_id,
                worker_id=self.worker_id,
                task_type=task_type,
                side_effect_class=side_effect_class,
                reason=reason,
            )
        except Exception as exc:
            session.rollback()
            logger.critical(
                "dispatcher_completion_failure_block_failed",
                extra={
                    "task_id": str(task_id),
                    "lease_id": str(lease_id),
                    "task_type": task_type,
                    "side_effect_class": side_effect_class,
                    "block_error": str(exc),
                    "original_error": reason,
                },
            )
        finally:
            session.close()

    def _fail(self, *, lease_id: uuid.UUID, reason: str) -> None:
        session = self._open_tenant_session()
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
        session = self._open_tenant_session()
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
def default_handler(task: ExecutionTask, context: TaskHandlerContext) -> dict[str, Any]:
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


@register_handler("force_fail")
def force_fail_handler(task: ExecutionTask, context: TaskHandlerContext) -> dict[str, Any]:
    raise RuntimeError("intentional failure for runtime validation")


@register_handler("echo", output_reason="echo handler completed")
def echo_handler(task: ExecutionTask, context: TaskHandlerContext) -> dict[str, Any]:
    """Return minimal proof-of-work output for persistence after completion succeeds."""

    payload = task.metadata_json.get("input", {})
    if not isinstance(payload, dict):
        raise ValueError("echo task input must be an object")

    return {
        "handler": "echo",
        "input": payload,
        "output": payload,
        "status": "completed",
    }


# Import additive handler package after built-in registrations so modular task
# handlers register through the same dispatcher registry without altering worker
# loop, queue, lease, or runtime state-machine authority.
from backend.workers import handlers as _registered_handlers  # noqa: E402,F401
