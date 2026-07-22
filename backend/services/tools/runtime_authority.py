from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.services.abilities.catalog import ABILITY_MANIFESTS_BY_ACTION
from backend.services.abilities.rollout_validation import validate_action_manifest_alignment
from backend.services.credentials.runtime_authority import CredentialRuntimeAuthority, CredentialRuntimeAuthorityError
from backend.services.tools.action_registry import ActionDefinition, ActionRegistry, get_default_action_registry
from backend.services.tools.capability_validation import (
    CapabilityActionValidationError,
    validate_capability_action_authority,
)
from backend.services.tools.mission_input_binding import (
    DependencyNotReadyError,
    InputBindingError,
    bind_tool_invocation_for_task,
)
from backend.services.tools.schemas import (
    ActionRuntimeContext,
    CredentialReference,
    RuntimeCredentialMaterial,
    SideEffectClass,
    ToolInvocation,
)


class ToolRuntimeAuthorityError(ValueError):
    """Raised when a tool invocation fails the runtime authority lane."""


class ToolRuntimeAuthority:
    """Runtime-authoritative gate for ``tool.invoke`` task execution.

    This service deliberately does not complete or fail worker runtime state. It
    validates the task-scoped tool invocation, concrete action authority, and
    side-effect envelope before delegating to ``ActionRegistry``. Dispatcher and
    ``WorkerRuntimeService`` remain the only completion/failure owners.

    Before invoke, lease-scoped mission input binding rebinds upstream ability
    outputs into tool_invocation.input when dependency_keys / input_bindings exist.
    """

    def __init__(
        self,
        *,
        registry: ActionRegistry | None = None,
        credential_authority: CredentialRuntimeAuthority | None = None,
    ) -> None:
        self._registry = registry or get_default_action_registry()
        self._credential_authority = credential_authority or CredentialRuntimeAuthority()

    def execute(self, *, task: ExecutionTask, context: Mapping[str, Any]) -> dict[str, Any]:
        binding_audit: dict[str, Any] = {}
        try:
            rebound_invocation, binding_audit = bind_tool_invocation_for_task(
                task=task,
                session_factory=context["session_factory"],
            )
            # Persist rebound input on the in-memory task for this invoke.
            # WorkerRuntimeService.complete mirrors handler output separately.
            if isinstance(task.metadata_json, dict) and rebound_invocation and not binding_audit.get("skipped"):
                task.metadata_json = {
                    **task.metadata_json,
                    "tool_invocation": rebound_invocation,
                    "input_binding_audit": binding_audit,
                }
        except DependencyNotReadyError:
            raise
        except InputBindingError as exc:
            raise ToolRuntimeAuthorityError(f"tool.invoke input binding failed: {exc}") from exc

        invocation, action, effective_side_effect_class = self.authorize(task=task, context=context)
        runtime_credentials = {}
        resolved_credential = self._resolve_runtime_credential(
            task=task,
            invocation=invocation,
            action=action,
            side_effect_class=effective_side_effect_class,
        )
        if resolved_credential is not None:
            runtime_credentials[action.name] = resolved_credential
            plugin_provider = resolved_credential.reference.provider
            if plugin_provider != action.provider:
                runtime_credentials[plugin_provider] = resolved_credential
        runtime_context = ActionRuntimeContext(
            tenant_id=task.tenant_id,
            task_id=task.id,
            mission_id=task.mission_id,
            worker_id=str(context["worker_id"]),
            lease_id=str(context["lease_id"]),
            session_factory=context["session_factory"],
            vector_session_factory=context.get("vector_session_factory"),
            runtime_credentials=runtime_credentials,
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
            "input_binding_audit": binding_audit,
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
        try:
            self._credential_authority.reject_raw_secret_metadata(metadata=task.metadata_json)
        except CredentialRuntimeAuthorityError as exc:
            raise ToolRuntimeAuthorityError(f"tool.invoke credential denied: {exc}") from exc
        raw_invocation = task.metadata_json.get("tool_invocation")
        if not isinstance(raw_invocation, dict):
            raise ToolRuntimeAuthorityError("tool.invoke requires metadata_json.tool_invocation object")
        try:
            invocation = ToolInvocation.model_validate(raw_invocation)
        except ValidationError as exc:
            raise ToolRuntimeAuthorityError("invalid tool_invocation") from exc
        invocation = self._enrich_invocation_from_metadata(invocation=invocation, metadata=task.metadata_json)

        action = self._registry.get(invocation.action)
        self._validate_ability_manifest(action)
        effective_side_effect_class = action.side_effect_for(invocation)
        if effective_side_effect_class.has_side_effect and task.status != ExecutionTaskState.RUNNING.value:
            raise ToolRuntimeAuthorityError("side-effecting tool.invoke action requires running task state")

        session_factory = context["session_factory"]
        session = session_factory()
        try:
            try:
                validate_capability_action_authority(
                    session=session,
                    tenant_id=task.tenant_id,
                    metadata=task.metadata_json,
                    action=action,
                    side_effect_class=effective_side_effect_class,
                )
            except CapabilityActionValidationError as exc:
                raise ToolRuntimeAuthorityError(f"tool.invoke promotion denied: {exc}") from exc
        finally:
            session.close()
        return invocation, action, effective_side_effect_class

    @staticmethod
    def _enrich_invocation_from_metadata(
        *,
        invocation: ToolInvocation,
        metadata: Mapping[str, Any],
    ) -> ToolInvocation:
        if invocation.credential_reference is not None:
            return invocation
        raw_reference = metadata.get("credential_reference")
        if not isinstance(raw_reference, Mapping):
            return invocation
        try:
            credential_reference = CredentialReference.model_validate(raw_reference)
        except ValidationError:
            return invocation
        return invocation.model_copy(update={"credential_reference": credential_reference})

    def _resolve_runtime_credential(
        self,
        *,
        task: ExecutionTask,
        invocation: ToolInvocation,
        action: ActionDefinition,
        side_effect_class: SideEffectClass,
    ) -> RuntimeCredentialMaterial | None:
        try:
            return self._credential_authority.resolve_for_action(
                tenant_id=task.tenant_id,
                invocation=invocation,
                metadata_reference=task.metadata_json.get("credential_reference"),
                action_name=action.name,
                provider=action.provider,
                side_effect_class=side_effect_class,
                requirement=action.credential_requirement,
            )
        except (CredentialRuntimeAuthorityError, ValidationError) as exc:
            raise ToolRuntimeAuthorityError(f"tool.invoke credential denied: {exc}") from exc

    @staticmethod
    def _validate_ability_manifest(action: ActionDefinition) -> None:
        manifest = ABILITY_MANIFESTS_BY_ACTION.get(action.name)
        if manifest is None:
            raise ToolRuntimeAuthorityError(f"tool.invoke action {action.name!r} has no ability manifest")
        try:
            validate_action_manifest_alignment(action_definition=action, manifest=manifest)
        except ValueError as exc:
            raise ToolRuntimeAuthorityError(
                f"tool.invoke action {action.name!r} ability manifest is invalid: {exc}"
            ) from exc
