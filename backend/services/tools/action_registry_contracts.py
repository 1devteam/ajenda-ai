from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel

from backend.services.credentials.runtime_authority import CredentialRequirement
from backend.services.tools.schemas import ActionResult, ActionRuntimeContext, SideEffectClass, ToolInvocation

ActionHandler = Callable[[ToolInvocation, ActionRuntimeContext], ActionResult]
SideEffectResolver = Callable[[ToolInvocation], SideEffectClass]


@dataclass(frozen=True, slots=True)
class ActionDefinition:
    """Declarative action contract shared by registration modules and the registry."""

    name: str
    handler: ActionHandler
    side_effect_class: SideEffectClass = SideEffectClass.NONE
    provider: str = "local"
    required_tools: tuple[str, ...] = field(default_factory=tuple)
    required_permissions: tuple[str, ...] = field(default_factory=tuple)
    input_model: type[BaseModel] | None = None
    aliases: tuple[str, ...] = field(default_factory=tuple)
    side_effect_resolver: SideEffectResolver | None = None
    credential_requirement: CredentialRequirement | None = None

    def side_effect_for(self, invocation: ToolInvocation) -> SideEffectClass:
        if self.side_effect_resolver is None:
            return self.side_effect_class
        return self.side_effect_resolver(invocation)


class ActionRegistryPort(Protocol):
    """Registration-only boundary used by action modules."""

    def register(self, definition: ActionDefinition) -> None: ...
