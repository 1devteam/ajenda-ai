from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from backend.domain.execution_task import ExecutionTask
from backend.services.tools.action_registry import ActionRegistryError, default_action_registry
from backend.services.tools.capability_validation import validate_capability_action_references
from backend.services.tools.schemas import ActionExecutionContext, ToolInvocationEnvelope
from backend.workers.task_dispatcher import TaskHandlerContext, register_handler

logger = logging.getLogger("ajenda.tool_invoke")


@register_handler("tool.invoke", output_reason="tool action completed")
def tool_invoke_handler(task: ExecutionTask, context: TaskHandlerContext) -> dict[str, Any]:
    """Execute a registered tool action through the existing dispatcher contract."""

    tenant_id = context["tenant_id"]
    if task.tenant_id != tenant_id:
        raise ValueError("tool.invoke task tenant does not match runtime context tenant")
    metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
    raw_invocation = metadata.get("tool_invocation")
    if not isinstance(raw_invocation, dict):
        raise ValueError('tool.invoke metadata must include object "tool_invocation"')
    try:
        invocation = ToolInvocationEnvelope.model_validate(raw_invocation)
    except ValidationError as exc:
        raise ValueError(f"invalid tool invocation payload: {exc.errors(include_url=False)}") from exc

    registry = default_action_registry()
    action_definition = registry.get(invocation.action)
    validation = _validate_capability_adapter_metadata(
        task=task,
        context=context,
        action=action_definition,
        task_type="tool.invoke",
    )
    action_context = ActionExecutionContext(
        tenant_id=tenant_id,
        task_id=task.id,
        mission_id=task.mission_id,
        worker_id=context["worker_id"],
        lease_id=context["lease_id"],
        session_factory=context["session_factory"],
        provider=invocation.provider,
    )
    try:
        action_result = registry.invoke(name=invocation.action, payload=invocation.input, context=action_context)
    except ActionRegistryError:
        raise
    except ValidationError as exc:
        raise ValueError(f"invalid action payload or result: {exc.errors(include_url=False)}") from exc

    result = {
        "handler": "tool.invoke",
        "status": "completed",
        "schema_version": 1,
        "action": action_result.action,
        "requested_action": invocation.action,
        "side_effect_class": action_result.side_effect_class,
        "output": action_result.output,
        "evidence": [item.model_dump(mode="json") for item in action_result.evidence],
        "runtime_context": {
            "tenant_id": tenant_id,
            "task_id": str(task.id),
            "mission_id": str(task.mission_id),
            "worker_id": context["worker_id"],
            "lease_id": context["lease_id"],
        },
        "capability_validation": {
            "capability_id": validation.capability_id,
            "adapter_id": validation.adapter_id,
            "warnings": list(validation.warnings),
        },
    }
    logger.info(
        "tool_action_completed",
        extra={"task_id": str(task.id), "action": action_result.action, "tenant_id": tenant_id},
    )
    return result


def _validate_capability_adapter_metadata(
    *,
    task: ExecutionTask,
    context: TaskHandlerContext,
    action: Any,
    task_type: str,
) -> Any:
    session = context["session_factory"]()
    try:
        return validate_capability_action_references(
            session=session,
            tenant_id=context["tenant_id"],
            task_type=task_type,
            action=action,
            capability_reference=task.metadata_json.get("capability_reference"),
            adapter_reference=task.metadata_json.get("adapter_reference"),
        )
    finally:
        session.close()
