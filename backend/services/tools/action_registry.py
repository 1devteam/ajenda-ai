from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from backend.services.tools.schemas import ActionExecutionContext, ActionResult, SideEffectClass

ActionCallable = Callable[[dict[str, Any], ActionExecutionContext], ActionResult | dict[str, Any]]


class ActionRegistryError(ValueError):
    """Raised for invalid action registration or invocation."""


@dataclass(frozen=True, slots=True)
class ActionDefinition:
    """Executable action definition registered in code, not in capability records."""

    name: str
    handler: ActionCallable
    schema_version: int = 1
    side_effect_class: SideEffectClass = "none"
    required_permissions: tuple[str, ...] = ()
    required_tools: tuple[str, ...] = ()
    evidence_types: tuple[str, ...] = ("action_result",)
    aliases: tuple[str, ...] = ()
    allowed_result_side_effect_classes: tuple[SideEffectClass, ...] = ()

    def __post_init__(self) -> None:
        normalized = self.name.strip()
        if not normalized:
            raise ActionRegistryError("action name must be a non-empty string")
        object.__setattr__(self, "name", normalized)
        if self.schema_version != 1:
            raise ActionRegistryError("action definition schema_version must be 1")


@dataclass(slots=True)
class ActionRegistry:
    """Deterministic in-process registry for executable tool actions."""

    _actions: dict[str, ActionDefinition] = field(default_factory=dict)

    def register(self, definition: ActionDefinition) -> ActionDefinition:
        names = (definition.name, *definition.aliases)
        normalized_names: list[str] = []
        for name in names:
            normalized = name.strip()
            if not normalized:
                raise ActionRegistryError("action alias must be a non-empty string")
            if normalized in self._actions:
                raise ActionRegistryError(f"action already registered: {normalized}")
            normalized_names.append(normalized)
        for name in normalized_names:
            self._actions[name] = definition
        return definition

    def get(self, name: str) -> ActionDefinition:
        normalized = name.strip()
        if not normalized:
            raise ActionRegistryError("action name must be a non-empty string")
        try:
            return self._actions[normalized]
        except KeyError as exc:
            raise ActionRegistryError(f"action is not registered: {normalized}") from exc

    def list_actions(self) -> list[str]:
        return sorted(self._actions)

    def invoke(self, *, name: str, payload: dict[str, Any], context: ActionExecutionContext) -> ActionResult:
        definition = self.get(name)
        raw_result = definition.handler(payload, context)
        result = raw_result if isinstance(raw_result, ActionResult) else ActionResult.model_validate(raw_result)
        if result.action != definition.name and result.action not in definition.aliases:
            raise ActionRegistryError("action result action does not match registered action")
        allowed_side_effects = definition.allowed_result_side_effect_classes or (definition.side_effect_class,)
        if result.side_effect_class not in allowed_side_effects:
            raise ActionRegistryError("action result side_effect_class does not match registered action")
        try:
            json.dumps(result.model_dump(mode="json"))
        except (TypeError, ValueError) as exc:
            raise ActionRegistryError("action result must be JSON serializable") from exc
        return result


_DEFAULT_REGISTRY: ActionRegistry | None = None


def build_default_action_registry() -> ActionRegistry:
    from backend.services.tools.calendar_actions import register_calendar_actions
    from backend.services.tools.http_actions import register_http_actions
    from backend.services.tools.sales_actions import register_sales_actions
    from backend.services.tools.webhook_actions import register_webhook_actions

    registry = ActionRegistry()
    register_sales_actions(registry)
    register_http_actions(registry)
    register_webhook_actions(registry)
    register_calendar_actions(registry)
    return registry


def default_action_registry() -> ActionRegistry:
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = build_default_action_registry()
    return _DEFAULT_REGISTRY
