from __future__ import annotations

import uuid

import pytest

from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.runtime_authority import ToolRuntimeAuthority, ToolRuntimeAuthorityError
from backend.services.tools.schemas import ActionResult, ActionRuntimeContext, SideEffectClass, ToolInvocation


class _Session:
    def close(self) -> None:
        pass


def _session_factory() -> _Session:
    return _Session()


def _handler(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    return ActionResult(action="unmanifested.action", provider="test", output={}, evidence=[], summary="done")


def _task(
    *,
    action: str = "record.search",
    input_payload: dict | None = None,
    metadata: dict | None = None,
    status: str = ExecutionTaskState.RUNNING.value,
) -> ExecutionTask:
    metadata_json = {"tool_invocation": {"action": action, "input": input_payload or {}}}
    if metadata:
        metadata_json.update(metadata)
    return ExecutionTask(
        id=uuid.uuid4(),
        tenant_id="tenant",
        mission_id=uuid.uuid4(),
        title="Tool task",
        description="Tool task",
        status=status,
        metadata_json=metadata_json,
    )


def _context(tenant_id: str = "tenant") -> dict[str, object]:
    return {
        "tenant_id": tenant_id,
        "worker_id": "worker-1",
        "lease_id": "lease-1",
        "session_factory": _session_factory,
    }


def test_runtime_authority_denies_registered_action_without_ability_manifest() -> None:
    registry = ActionRegistry()
    registry.register(
        ActionDefinition(
            name="unmanifested.action",
            handler=_handler,
            provider="test",
            side_effect_class=SideEffectClass.NONE,
        )
    )
    registry.freeze()

    with pytest.raises(ToolRuntimeAuthorityError, match="has no ability manifest"):
        ToolRuntimeAuthority(registry=registry).authorize(
            task=_task(action="unmanifested.action"),
            context=_context(),
        )


def test_runtime_authority_returns_deterministic_promotion_denial(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.services.tools import runtime_authority

    class PromotionDenied(runtime_authority.CapabilityActionValidationError):
        pass

    def deny_with_capability_error(**kwargs: object) -> None:
        raise PromotionDenied("runtime promotion requires explicit capability/adapter authority")

    monkeypatch.setattr(runtime_authority, "validate_capability_action_authority", deny_with_capability_error)

    with pytest.raises(
        ToolRuntimeAuthorityError,
        match=r"tool\.invoke promotion denied: runtime promotion requires explicit capability/adapter authority",
    ):
        ToolRuntimeAuthority().authorize(
            task=_task(action="http.request", input_payload={"url": "https://example.com"}),
            context=_context(),
        )
