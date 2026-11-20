from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, TypedDict

from backend.domain.execution_task import ExecutionTask

logger = logging.getLogger("ajenda.task_dispatcher")


class TaskHandlerContext(TypedDict, total=False):
    """Runtime context passed into task handlers."""

    worker_id: str
    tenant_id: str
    lease_id: str
    session_factory: Any
    vector_session_factory: Any


TaskHandler = Callable[[ExecutionTask, TaskHandlerContext], dict[str, Any]]

HANDLER_REGISTRY: dict[str, TaskHandler] = {}
OUTPUT_REASON_BY_TASK_TYPE: dict[str, str] = {}


def normalize_task_type(task_type: str) -> str:
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


def register_handler(
    task_type: str,
    *,
    output_reason: str | None = None,
    registry: dict[str, TaskHandler] | None = None,
    output_reasons: dict[str, str] | None = None,
) -> Callable[[TaskHandler], TaskHandler]:
    """Register a handler without depending on dispatcher execution."""

    normalized_task_type = normalize_task_type(task_type)
    normalized_output_reason = _normalize_output_reason(output_reason)
    target_registry = HANDLER_REGISTRY if registry is None else registry
    target_output_reasons = OUTPUT_REASON_BY_TASK_TYPE if output_reasons is None else output_reasons

    def decorator(fn: TaskHandler) -> TaskHandler:
        if normalized_task_type in target_registry:
            raise ValueError(f"task handler already registered for task_type='{normalized_task_type}'")
        target_registry[normalized_task_type] = fn
        if normalized_output_reason is not None:
            target_output_reasons[normalized_task_type] = normalized_output_reason
        logger.info("task_handler_registered", extra={"task_type": normalized_task_type})
        return fn

    return decorator
