from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel, ValidationError

from backend.services.credentials.runtime_authority import CredentialRequirement
from backend.services.security.redaction import contains_sensitive_value, redact_sensitive_data
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
    credential_requirement: CredentialRequirement | None = None

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
            credential_requirement=definition.credential_requirement,
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
                raise ValueError(f"invalid input for action {definition.name}") from exc
        sensitive_values = _runtime_credential_values(context)
        result = definition.handler(invocation, context)
        try:
            parsed = ActionResult.model_validate(result)
            # Force a fresh validation pass even when the handler returned an
            # ActionResult instance. Pydantic's default instance revalidation can
            # otherwise return a mutated/model_construct instance as-is.
            redacted_payload = _redact_action_result_payload(
                parsed.model_dump(mode="json"), sensitive_values=sensitive_values
            )
            validated = ActionResult.model_validate(redacted_payload)
            if _contains_action_result_sensitive_value(validated.model_dump(mode="json"), sensitive_values):
                raise ValueError("action result contains runtime credential material")
        except ValidationError as exc:
            raise ValueError(f"action {definition.name} must return valid ActionResult: {exc}") from exc
        self._validate_result_contract(definition=definition, invocation=invocation, context=context, result=validated)
        try:
            json.dumps(validated.model_dump(mode="json"))
        except (TypeError, ValueError) as exc:
            raise ValueError("action result must be JSON serializable") from exc
        return validated

    def _validate_result_contract(
        self,
        *,
        definition: ActionDefinition,
        invocation: ToolInvocation,
        context: ActionRuntimeContext,
        result: ActionResult,
    ) -> None:
        expected_side_effect_class = definition.side_effect_for(invocation)
        if result.action != definition.name:
            raise ValueError("action result action must match registered canonical action")
        if result.provider != definition.provider:
            raise ValueError("action result provider must match registered action provider")
        if result.side_effect_class != expected_side_effect_class:
            raise ValueError("action result side_effect_class must match effective action side_effect_class")
        if not result.evidence:
            raise ValueError("action result must include at least one EvidenceItem")
        for evidence_item in result.evidence:
            if evidence_item.action_name != definition.name:
                raise ValueError("action evidence action_name must match registered canonical action")
            if evidence_item.tool_provider != result.provider:
                raise ValueError("action evidence tool_provider must match action result provider")
            if evidence_item.side_effect_class != result.side_effect_class:
                raise ValueError("action evidence side_effect_class must match action result side_effect_class")
            if evidence_item.tenant_id != context.tenant_id:
                raise ValueError("action evidence tenant_id must match runtime context tenant_id")
            if evidence_item.task_id != str(context.task_id):
                raise ValueError("action evidence task_id must match runtime context task_id")
            expected_mission_id = str(context.mission_id) if context.mission_id is not None else None
            if evidence_item.mission_id != expected_mission_id:
                raise ValueError("action evidence mission_id must match runtime context mission_id")

    @property
    def actions(self) -> Mapping[str, ActionDefinition]:
        return MappingProxyType(dict(self._actions))


USER_CONTROLLED_ACTION_RESULT_MAPS = ("output",)
USER_CONTROLLED_EVIDENCE_MAPS = ("structured_payload", "provenance")
USER_CONTROLLED_EVIDENCE_TEXT_FIELDS = (
    "evidence_source",
    "summary",
    "records_inspected",
    "records_changed",
    "limitations",
    "collection_status",
)


def _redact_action_result_payload(payload: dict[str, Any], *, sensitive_values: tuple[str, ...]) -> dict[str, Any]:
    redacted = dict(payload)
    for field_name in USER_CONTROLLED_ACTION_RESULT_MAPS:
        redacted[field_name] = redact_sensitive_data(
            redacted.get(field_name, {}),
            additional_sensitive_values=sensitive_values,
            redact_mapping_keys=True,
        )
    for field_name in ("records_inspected", "records_changed", "summary", "limitations"):
        redacted[field_name] = redact_sensitive_data(
            redacted.get(field_name), additional_sensitive_values=sensitive_values
        )
    evidence_items = redacted.get("evidence", [])
    if isinstance(evidence_items, list):
        redacted["evidence"] = [
            _redact_evidence_payload(evidence_item, sensitive_values=sensitive_values)
            for evidence_item in evidence_items
        ]
    return redacted


def _redact_evidence_payload(evidence_item: Any, *, sensitive_values: tuple[str, ...]) -> Any:
    if not isinstance(evidence_item, dict):
        return evidence_item
    redacted = dict(evidence_item)
    for field_name in USER_CONTROLLED_EVIDENCE_MAPS:
        redacted[field_name] = redact_sensitive_data(
            redacted.get(field_name, {}),
            additional_sensitive_values=sensitive_values,
            redact_mapping_keys=True,
        )
    for field_name in USER_CONTROLLED_EVIDENCE_TEXT_FIELDS:
        redacted[field_name] = redact_sensitive_data(
            redacted.get(field_name), additional_sensitive_values=sensitive_values
        )
    return redacted


def _contains_action_result_sensitive_value(payload: dict[str, Any], sensitive_values: tuple[str, ...]) -> bool:
    return any(
        contains_sensitive_value(value, sensitive_values, inspect_mapping_keys=True)
        for value in _user_controlled_payload_values(payload)
    )


def _user_controlled_payload_values(payload: dict[str, Any]) -> tuple[Any, ...]:
    values: list[Any] = [payload.get(field_name, {}) for field_name in USER_CONTROLLED_ACTION_RESULT_MAPS]
    values.extend(
        payload.get(field_name) for field_name in ("records_inspected", "records_changed", "summary", "limitations")
    )
    evidence_items = payload.get("evidence", [])
    if isinstance(evidence_items, list):
        for evidence_item in evidence_items:
            if not isinstance(evidence_item, dict):
                continue
            values.extend(evidence_item.get(field_name, {}) for field_name in USER_CONTROLLED_EVIDENCE_MAPS)
            values.extend(evidence_item.get(field_name) for field_name in USER_CONTROLLED_EVIDENCE_TEXT_FIELDS)
    return tuple(values)


def _runtime_credential_values(context: ActionRuntimeContext) -> tuple[str, ...]:
    values: list[str] = []
    for credential in context.runtime_credentials.values():
        values.append(credential.secret_value)
        values.extend(credential.injected_headers.values())
    return tuple(value for value in values if value)


def _normalize_action_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise ValueError("action name must be non-empty")
    return normalized


_DEFAULT_REGISTRY: ActionRegistry | None = None


def build_default_action_registry() -> ActionRegistry:
    from backend.services.tools.calendar_actions import register_calendar_actions
    from backend.services.tools.gtm_actions import register_gtm_actions
    from backend.services.tools.http_actions import register_http_actions
    from backend.services.tools.linkedin_actions import register_linkedin_actions
    from backend.services.tools.provider_read_actions import register_provider_read_actions
    from backend.services.tools.salesforce_actions import register_salesforce_actions
    from backend.services.tools.sales_actions import register_sales_actions
    from backend.services.tools.standalone_actions import register_standalone_actions
    from backend.services.tools.webhook_actions import register_webhook_actions

    registry = ActionRegistry()
    register_sales_actions(registry)
    register_http_actions(registry)
    register_provider_read_actions(registry)
    register_linkedin_actions(registry)
    register_salesforce_actions(registry)
    register_webhook_actions(registry)
    register_calendar_actions(registry)
    register_gtm_actions(registry)
    register_standalone_actions(registry)
    registry.freeze()
    return registry


def get_default_action_registry(*, rebuild: bool = False) -> ActionRegistry:
    global _DEFAULT_REGISTRY
    if rebuild or _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = build_default_action_registry()
    return _DEFAULT_REGISTRY
