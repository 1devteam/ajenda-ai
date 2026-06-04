from __future__ import annotations

import uuid
from typing import Any

import pytest

from backend.services.tools.action_registry import ActionDefinition, ActionRegistry, ActionRegistryError
from backend.services.tools.schemas import ActionExecutionContext, ActionResult


def _context() -> ActionExecutionContext:
    return ActionExecutionContext(
        tenant_id="tenant-a",
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        worker_id="worker-a",
        lease_id=str(uuid.uuid4()),
        session_factory=lambda: None,
    )


def test_action_registry_registers_and_invokes_action() -> None:
    registry = ActionRegistry()

    def handler(payload: dict[str, Any], context: ActionExecutionContext) -> ActionResult:
        return ActionResult(action="demo.action", output={"tenant_id": context.tenant_id, "payload": payload})

    registry.register(ActionDefinition(name="demo.action", handler=handler))

    result = registry.invoke(name="demo.action", payload={"x": 1}, context=_context())

    assert result.action == "demo.action"
    assert result.output == {"tenant_id": "tenant-a", "payload": {"x": 1}}


def test_action_registry_rejects_blank_action_name() -> None:
    with pytest.raises(ActionRegistryError, match="action name must be"):
        ActionDefinition(name="   ", handler=lambda payload, context: ActionResult(action="bad"))


def test_action_registry_rejects_duplicate_names_and_aliases() -> None:
    registry = ActionRegistry()

    def handler(payload: dict[str, Any], context: ActionExecutionContext) -> ActionResult:
        return ActionResult(action="demo.action")

    registry.register(ActionDefinition(name="demo.action", handler=handler, aliases=("demo.alias",)))

    with pytest.raises(ActionRegistryError, match="already registered"):
        registry.register(ActionDefinition(name="other.action", handler=handler, aliases=("demo.alias",)))


def test_action_registry_fails_closed_on_missing_action() -> None:
    registry = ActionRegistry()

    with pytest.raises(ActionRegistryError, match="action is not registered"):
        registry.invoke(name="missing.action", payload={}, context=_context())


def test_action_registry_rejects_invalid_result_shape() -> None:
    registry = ActionRegistry()
    registry.register(ActionDefinition(name="bad.action", handler=lambda payload, context: {"status": "completed"}))

    with pytest.raises(ValueError):
        registry.invoke(name="bad.action", payload={}, context=_context())
