from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from pydantic import BaseModel, ValidationError

from backend.services.tools.schemas import ActionResult, ActionRuntimeContext, SideEffectClass, ToolInvocation

ActionHandler = Callable[[ToolInvocation, ActionRuntimeContext], ActionResult]
SideEffectResolver = Callable[[ToolInvocation], SideEffectClass]


@dataclass(frozen=True, slots=True)
class ActionDefinition:
    name: str
    handler: ActionHandler
    side_effect_class: SideEffectClass = SideEffectClass.NONE
    provider: str = "local"
    required_tools: tuple[str, ...] = field(default_factory=tuple)
    required_permissions: tuple[str, ...] = field(default_factory=tuple)
    input_model: type[BaseModel] | None = None
    aliases: tuple[str, ...] = field(default_factory=tuple)
    side_effect_resolver: SideEffectResolver | None = None

    def side_effect_for(self, invocation: ToolInvocation) -> SideEffectClass:
        if self.side_effect_resolver is None:
            return self.side_effect_class
        return self.side_effect_resolver(invocation)


class ActionRegistry:
    def __init__(self) -> None:
        self._actions: dict[str, ActionDefinition] = {}
        self._frozen = False

    def register(self, definition: ActionDefinition) -> None:
        if self._frozen:
            raise ValueError("action registry is frozen")
        normalized_name = _normalize_action_name(definition.name)
        names = (normalized_name, *(_normalize_action_name(alias) for alias in definition.aliases))
        for name in names:
            if name in self._actions:
                raise ValueError(f"action already registered: {name}")
        normalized_definition = ActionDefinition(
            name=normalized_name,
            handler=definition.handler,
            side_effect_class=definition.side_effect_class,
            provider=definition.provider,
            required_tools=tuple(definition.required_tools),
            required_permissions=tuple(definition.required_permissions),
            input_model=definition.input_model,
            aliases=tuple(_normalize_action_name(alias) for alias in definition.aliases),
            side_effect_resolver=definition.side_effect_resolver,
        )
        for name in names:
            self._actions[name] = normalized_definition

    def freeze(self) -> None:
        self._frozen = True

    def get(self, name: str) -> ActionDefinition:
        normalized_name = _normalize_action_name(name)
        definition = self._actions.get(normalized_name)
        if definition is None:
            raise ValueError(f"unknown action: {normalized_name}")
        return definition

    def invoke(self, invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
        definition = self.get(invocation.action)
        if definition.input_model is not None:
            try:
                definition.input_model.model_validate(invocation.input)
            except ValidationError as exc:
                raise ValueError(f"invalid input for action {definition.name}: {exc}") from exc
        result = definition.handler(invocation, context)
        validated = ActionResult.model_validate(result.model_dump(mode="json"))
        try:
            json.dumps(validated.model_dump(mode="json"))
        except (TypeError, ValueError) as exc:
            raise ValueError("action result must be JSON serializable") from exc
        return validated

    @property
    def actions(self) -> Mapping[str, ActionDefinition]:
        return MappingProxyType(dict(self._actions))


def _normalize_action_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise ValueError("action name must be non-empty")
    return normalized


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
    registry.freeze()
    return registry


def get_default_action_registry(*, rebuild: bool = False) -> ActionRegistry:
    global _DEFAULT_REGISTRY
    if rebuild or _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = build_default_action_registry()
    return _DEFAULT_REGISTRY
