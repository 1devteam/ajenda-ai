from __future__ import annotations

from backend.services.tools.action_registry import ActionDefinition
from backend.services.tools.capability_validation import _validate_task_or_tool_allowed
from backend.services.tools.schemas import ActionResult


def _definition() -> ActionDefinition:
    return ActionDefinition(name="record.search", handler=lambda payload, context: ActionResult(action="record.search"))


def test_capability_action_validation_allows_task_type_match() -> None:
    _validate_task_or_tool_allowed(
        label="capability",
        supported_task_types=["tool.invoke"],
        required_tools=[],
        task_type="tool.invoke",
        action=_definition(),
    )


def test_capability_action_validation_allows_required_tool_match() -> None:
    _validate_task_or_tool_allowed(
        label="capability",
        supported_task_types=[],
        required_tools=["record.search"],
        task_type="tool.invoke",
        action=_definition(),
    )


def test_capability_action_validation_rejects_unsupported_task_type() -> None:
    try:
        _validate_task_or_tool_allowed(
            label="capability",
            supported_task_types=["calendar.read"],
            required_tools=[],
            task_type="tool.invoke",
            action=_definition(),
        )
    except ValueError as exc:
        assert str(exc) == "capability does not support task_type or action"
    else:  # pragma: no cover - assertion guard
        raise AssertionError("unsupported task type should fail closed")


def test_capability_action_validation_rejects_required_tool_mismatch() -> None:
    try:
        _validate_task_or_tool_allowed(
            label="adapter",
            supported_task_types=[],
            required_tools=["calendar.read"],
            task_type="tool.invoke",
            action=_definition(),
        )
    except ValueError as exc:
        assert str(exc) == "adapter required_tools do not allow action"
    else:  # pragma: no cover - assertion guard
        raise AssertionError("required tool mismatch should fail closed")
