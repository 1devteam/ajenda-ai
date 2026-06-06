from __future__ import annotations

import uuid

import pytest

from backend.services.tools.action_registry import ActionDefinition, ActionRegistry, get_default_action_registry
from backend.services.tools.schemas import ActionResult, ActionRuntimeContext, ToolInvocation


def _context() -> ActionRuntimeContext:
    return ActionRuntimeContext(
        tenant_id=str(uuid.uuid4()),
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        worker_id="worker-test",
        lease_id=str(uuid.uuid4()),
    )


def test_action_registry_registers_and_invokes_action() -> None:
    registry = ActionRegistry()

    def handler(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
        return ActionResult(
            action="custom.action", provider="test", output={"echo": invocation.input}, summary="custom action done"
        )

    registry.register(ActionDefinition(name="custom.action", handler=handler))

    result = registry.invoke(ToolInvocation(action="custom.action", input={"value": 7}), _context())

    assert result.action == "custom.action"
    assert result.output == {"echo": {"value": 7}}


def test_action_registry_rejects_duplicate_action_names() -> None:
    registry = ActionRegistry()

    def handler(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
        return ActionResult(action="dup.action", provider="test", output={}, summary="done")

    registry.register(ActionDefinition(name="dup.action", handler=handler))

    with pytest.raises(ValueError, match="action already registered"):
        registry.register(ActionDefinition(name="dup.action", handler=handler))


def test_action_registry_fails_closed_on_unknown_action() -> None:
    registry = ActionRegistry()

    with pytest.raises(ValueError, match="unknown action"):
        registry.get("missing.action")


def test_default_registry_is_frozen_and_stable() -> None:
    registry = get_default_action_registry(rebuild=True)
    first_names = sorted(registry.actions)

    with pytest.raises(ValueError, match="frozen"):
        registry.register(
            ActionDefinition(
                name="late.action",
                handler=lambda invocation, context: ActionResult(
                    action="late.action", provider="test", output={}, summary="late"
                ),
            )
        )

    assert sorted(get_default_action_registry().actions) == first_names
    assert "tool.invoke" not in first_names
    assert {
        "record.search",
        "http.request",
        "webhook.dispatch",
        "calendar.create_event",
        "crm.research",
        "gtm.message_draft",
    }.issubset(first_names)
