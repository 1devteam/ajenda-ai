from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.services.tools.action_registry import ActionDefinition, ActionRegistry, get_default_action_registry
from backend.services.tools.capability_validation import validate_capability_action_authority
from backend.services.tools.schemas import ActionRuntimeContext, SideEffectClass, ToolInvocation


class ToolRuntimeAuthorityError(ValueError):
    """Raised when a tool invocation fails the runtime authority lane."""


class ToolRuntimeAuthority:
    """Runtime-authoritative gate for ``tool.invoke`` task execution.

    This service deliberately does not complete or fail worker runtime state. It
    validates the task-scoped tool invocation, concrete action authority, and
    side-effect envelope before delegating to ``ActionRegistry``. Dispatcher and
    ``WorkerRuntimeService`` remain the only completion/failure owners.
    """

    def __init__(self, *, registry: ActionRegistry | None = None) -> None:
        self._registry = registry or get_default_action_registry()

    def execute(self, *, task: ExecutionTask, context: Mapping[str, Any]) -> dict[str, Any]:
        invocation, action, _effective_side_effect_class = self.authorize(task=task, context=context)
        runtime_context = ActionRuntimeContext(
            tenant_id=task.tenant_id,
            task_id=task.id,
            mission_id=task.mission_id,
            worker_id=str(context["worker_id"]),
            lease_id=str(context["lease_id"]),
            session_factory=context["session_factory"],
        )
        result = self._registry.invoke(invocation, runtime_context)
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
                "worker_id": str(context["worker_id"]),
                "lease_id": str(context["lease_id"]),
            },
        }

    def authorize(
        self, *, task: ExecutionTask, context: Mapping[str, Any]
    ) -> tuple[ToolInvocation, ActionDefinition, SideEffectClass]:
        if task.tenant_id != context["tenant_id"]:
            raise ToolRuntimeAuthorityError("tool.invoke tenant mismatch")
        raw_invocation = task.metadata_json.get("tool_invocation")
        if not isinstance(raw_invocation, dict):
            raise ToolRuntimeAuthorityError("tool.invoke requires metadata_json.tool_invocation object")
        try:
            invocation = ToolInvocation.model_validate(raw_invocation)
        except ValidationError as exc:
            raise ToolRuntimeAuthorityError(f"invalid tool_invocation: {exc}") from exc

        action = self._registry.get(invocation.action)
        effective_side_effect_class = action.side_effect_for(invocation)
        if effective_side_effect_class.has_side_effect and task.status != ExecutionTaskState.RUNNING.value:
            raise ToolRuntimeAuthorityError("side-effecting tool.invoke action requires running task state")

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
        return invocation, action, effective_side_effect_class
