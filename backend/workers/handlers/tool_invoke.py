from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from backend.domain.execution_task import ExecutionTask
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.capability_validation import validate_capability_action_authority
from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation, side_effect_authorized
from backend.workers.task_dispatcher import TaskHandlerContext, register_handler


@register_handler("tool.invoke", output_reason="tool action completed")
def tool_invoke_handler(task: ExecutionTask, context: TaskHandlerContext) -> dict[str, Any]:
    if task.tenant_id != context["tenant_id"]:
        raise ValueError("tool.invoke tenant mismatch")
    raw_invocation = task.metadata_json.get("tool_invocation")
    if not isinstance(raw_invocation, dict):
        raise ValueError("tool.invoke requires metadata_json.tool_invocation object")
    try:
        invocation = ToolInvocation.model_validate(raw_invocation)
    except ValidationError as exc:
        raise ValueError(f"invalid tool_invocation: {exc}") from exc

    registry = get_default_action_registry()
    action = registry.get(invocation.action)
    effective_side_effect_class = action.side_effect_for(invocation)
    if effective_side_effect_class.has_side_effect and not side_effect_authorized(task.metadata_json, action.name):
        # Keep this fast gate before provider/action invocation. Deeper validation
        # below still checks capability/adapter metadata when references exist.
        if (
            task.metadata_json.get("capability_reference") is None
            and task.metadata_json.get("adapter_reference") is None
        ):
            raise ValueError("side-effecting action requires explicit capability/adapter authority")

    session_factory = context["session_factory"]
    session = session_factory()
    try:
        validate_capability_action_authority(
            session=session,
            tenant_id=task.tenant_id,
            metadata=task.metadata_json,
            action=action,
            side_effect_class=effective_side_effect_class,
        )
    finally:
        session.close()

    runtime_context = ActionRuntimeContext(
        tenant_id=task.tenant_id,
        task_id=task.id,
        mission_id=task.mission_id,
        worker_id=context["worker_id"],
        lease_id=context["lease_id"],
        session_factory=session_factory,
    )
    result = registry.invoke(invocation, runtime_context)
    result_payload = result.model_dump(mode="json")
    return {
        "handler": "tool.invoke",
        "status": "completed",
        "schema_version": 1,
        "action": action.name,
        "requested_action": invocation.action,
        "provider": result.provider,
        "side_effect_class": result.side_effect_class.value,
        "output": result_payload["output"],
        "evidence": result_payload["evidence"],
        "records_inspected": result_payload["records_inspected"],
        "records_changed": result_payload["records_changed"],
        "summary": result.summary,
        "confidence": result.confidence,
        "limitations": result.limitations,
        "runtime_context": {
            "tenant_id": task.tenant_id,
            "task_id": str(task.id),
            "mission_id": str(task.mission_id) if task.mission_id is not None else None,
            "worker_id": context["worker_id"],
            "lease_id": context["lease_id"],
        },
    }
