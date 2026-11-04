from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from backend.db.tenant_session import activate_tenant_session
from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.repositories.business_profile_repository import BusinessProfileRepository
from backend.services.abilities.catalog import ABILITY_MANIFESTS_BY_ACTION
from backend.services.abilities.manifest import AbilityManifest
from backend.services.abilities.rollout_validation import validate_action_manifest_alignment
from backend.services.abilities.runtime_governance import (
    ability_authorized,
    manifest_governance_snapshot,
)
from backend.services.credentials.runtime_authority import CredentialRuntimeAuthority, CredentialRuntimeAuthorityError
from backend.services.operating_charter import OperatingCharterViolation, assert_action_allowed, load_operating_charter
from backend.services.runtime_evidence_ledger import RuntimeCausalObservation, RuntimeEvidenceLedger
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
        if isinstance(task.metadata_json, dict):
            existing_observations = task.metadata_json.get("runtime_causal_observations")
            observations = list(existing_observations) if isinstance(existing_observations, list) else []
            observations.extend(
                [
                    RuntimeCausalObservation(
                        stage="input_binding",
                        decision="invocation_bound",
                        reason_code="dependency_binding"
                        if binding_audit and not binding_audit.get("skipped")
                        else "no_dependencies",
                        transformation_id="mission-input-binding:v1",
                        selected_path=action.name,
                        field_lineage={
                            "task.input": "upstream.artifact"
                            if not binding_audit.get("skipped")
                            else "task.declared_input",
                        },
                        safe_metadata={
                            "binding_skipped": bool(binding_audit.get("skipped")),
                            "binding_key_count": len(binding_audit.get("bindings_applied") or []),
                        },
                    ).model_dump(mode="json"),
                    RuntimeCausalObservation(
                        stage="provider_selection",
                        decision="provider_selected",
                        reason_code="registered_action_provider",
                        transformation_id="action-registry:provider-selection:v1",
                        selected_path=action.provider,
                        safe_metadata={"action": action.name, "side_effect_class": effective_side_effect_class.value},
                    ).model_dump(mode="json"),
                ]
            )
            task.metadata_json = {
                **task.metadata_json,
                "runtime_causal_observations": observations,
            }
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
        manifest = self._validate_ability_manifest(action)
        effective_side_effect_class = action.side_effect_for(invocation)
        if effective_side_effect_class.has_side_effect and task.status != ExecutionTaskState.RUNNING.value:
            raise ToolRuntimeAuthorityError("side-effecting tool.invoke action requires running task state")

        session_factory = context["session_factory"]
        session = session_factory()
        try:
            # This is a fresh worker transaction. Capability and adapter
            # visibility is tenant-scoped under forced RLS, so activate the
            # transaction-local tenant context before resolving authority.
            activate_tenant_session(session, task.tenant_id)
            # Composition authority is intentionally rechecked at the final
            # side-effect boundary.  A queued write/send must not remain
            # executable merely because an older charter allowed its plan.
            if effective_side_effect_class.has_side_effect:
                profile = BusinessProfileRepository(session).get_active_profile_for_tenant(tenant_id=task.tenant_id)
                facts = (
                    profile.approved_facts if profile is not None and isinstance(profile.approved_facts, dict) else {}
                )
                try:
                    charter = load_operating_charter(approved_facts=facts)
                    assert_action_allowed(
                        action_name=action.name,
                        side_effect_class=effective_side_effect_class,
                        charter=charter,
                    )
                except OperatingCharterViolation as exc:
                    self._record_charter_denial(
                        session=session,
                        task=task,
                        action_name=action.name,
                        side_effect_class=effective_side_effect_class,
                        code=exc.code,
                    )
                    raise ToolRuntimeAuthorityError(f"tool.invoke charter denied [{exc.code}]: {exc.message}") from exc
            try:
                validate_capability_action_authority(
                    session=session,
                    tenant_id=task.tenant_id,
                    metadata=task.metadata_json,
                    action=action,
                    side_effect_class=effective_side_effect_class,
                    task_id=task.id,
                )
            except CapabilityActionValidationError as exc:
                raise ToolRuntimeAuthorityError(f"tool.invoke promotion denied: {exc}") from exc

            if manifest is not None:
                approval_revalidated = (
                    ability_authorized(
                        task.metadata_json,
                        manifest=manifest,
                        tenant_id=task.tenant_id,
                        task_id=task.id,
                    )
                    if manifest.approval_required
                    else None
                )
                self._record_ability_governance_observation(
                    task=task,
                    manifest=manifest,
                    approval_revalidated=approval_revalidated,
                )
                if manifest.approval_required and not approval_revalidated:
                    self._record_ability_governance_denial(
                        session=session,
                        task=task,
                        manifest=manifest,
                    )
                    raise ToolRuntimeAuthorityError(
                        "tool.invoke ability manifest requires a current task-bound human approval"
                    )
        finally:
            session.close()
        return invocation, action, effective_side_effect_class

    @staticmethod
    def _record_charter_denial(
        *,
        session: Any,
        task: ExecutionTask,
        action_name: str,
        side_effect_class: SideEffectClass,
        code: str,
    ) -> None:
        """Record a current-charter denial before any provider call.

        This is the final pre-provider authorization boundary. A request that
        has already crossed a provider boundary may not be recallable, but a
        retry or recovery re-enters ``authorize`` and checks current authority
        again rather than reusing a historical approval decision.
        """
        # A normal worker task always belongs to a durable mission.  Some
        # controlled callers (including compatibility proofs) exercise this
        # boundary with a detached task object, however.  AuditEvent has a
        # foreign key to missions, so never turn a policy denial into a
        # database-integrity failure by claiming an unverified mission ID.
        # Preserve the original reference in the fact and use it for
        # correlation only when it is a persisted mission of this tenant.
        persisted_mission_id = None
        if task.mission_id is not None:
            persisted_mission_id = session.scalar(
                select(Mission.id).where(
                    Mission.id == task.mission_id,
                    Mission.tenant_id == task.tenant_id,
                )
            )
        RuntimeEvidenceLedger(session, flush=True).append_fact(
            tenant_id=task.tenant_id,
            mission_id=persisted_mission_id,
            category="operating_charter",
            action="side_effect_denied_at_execution",
            producer="tool_runtime_authority",
            actor="tool_runtime_authority",
            details="Current tenant charter denied a queued side-effect before provider invocation.",
            facts={
                "task_id": str(task.id),
                "action": action_name,
                "side_effect_class": side_effect_class.value,
                "reason_code": code,
                "enforcement_boundary": "pre_provider_invocation",
                "mission_reference_status": "persisted" if persisted_mission_id is not None else "unverified",
                "original_mission_id": str(task.mission_id) if task.mission_id is not None else None,
            },
            causation_id=str(task.id),
            correlation_id=str(persisted_mission_id) if persisted_mission_id is not None else None,
        )
        # ``authorize`` owns this fresh session; worker task/lease transitions
        # occur in WorkerRuntimeService's distinct transaction. Therefore this
        # commit persists only the denial fact and cannot commit caller-owned
        # task state. If it fails, authorization remains fail-closed.
        session.commit()

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
    def _validate_ability_manifest(action: ActionDefinition) -> AbilityManifest:
        manifest = ABILITY_MANIFESTS_BY_ACTION.get(action.name)
        if manifest is None:
            raise ToolRuntimeAuthorityError(f"tool.invoke action {action.name!r} has no ability manifest")
        try:
            validate_action_manifest_alignment(action_definition=action, manifest=manifest)
        except ValueError as exc:
            raise ToolRuntimeAuthorityError(
                f"tool.invoke action {action.name!r} ability manifest is invalid: {exc}"
            ) from exc
        return manifest

    @staticmethod
    def _record_ability_governance_observation(
        *, task: ExecutionTask, manifest: AbilityManifest, approval_revalidated: bool | None
    ) -> None:
        """Carry safe policy facts into the existing worker-owned audit ledger."""

        metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
        observations = metadata.get("runtime_causal_observations")
        items = list(observations) if isinstance(observations, list) else []
        capability_reference = metadata.get("capability_reference")
        adapter_reference = metadata.get("adapter_reference")
        snapshot = manifest_governance_snapshot(manifest)
        snapshot["capability_reference_present"] = isinstance(capability_reference, Mapping)
        snapshot["adapter_reference_present"] = isinstance(adapter_reference, Mapping)
        snapshot["ability_approval_revalidated"] = approval_revalidated
        items.append(
            RuntimeCausalObservation(
                stage="ability_governance",
                decision="ability_manifest_revalidated",
                reason_code=(
                    "human_approval_current"
                    if approval_revalidated
                    else "approval_not_required"
                    if approval_revalidated is None
                    else "human_approval_missing_or_invalid"
                ),
                transformation_id="ability-manifest-governance:v1",
                selected_path=manifest.ability_id,
                constraints=("manifest_alignment", "tenant_capability_adapter_authority"),
                safe_metadata=snapshot,
            ).model_dump(mode="json")
        )
        task.metadata_json = {**metadata, "ability_governance": snapshot, "runtime_causal_observations": items}

    @staticmethod
    def _record_ability_governance_denial(*, session: Any, task: ExecutionTask, manifest: AbilityManifest) -> None:
        """Persist a safe denial fact before a provider can be invoked.

        The worker records its terminal failure in its own transaction.  This
        fresh authority transaction additionally preserves why the provider
        boundary was closed, even if that later worker transition fails or is
        retried.  No invocation input, destination, credential, or external
        content enters the fact.
        """

        try:
            persisted_mission_id = None
            if task.mission_id is not None:
                persisted_mission_id = session.scalar(
                    select(Mission.id).where(
                        Mission.id == task.mission_id,
                        Mission.tenant_id == task.tenant_id,
                    )
                )
            snapshot = manifest_governance_snapshot(manifest)
            RuntimeEvidenceLedger(session, flush=True).append_fact(
                tenant_id=task.tenant_id,
                mission_id=persisted_mission_id,
                category="ability_governance",
                action="ability_approval_denied_at_execution",
                producer="tool_runtime_authority",
                actor="tool_runtime_authority",
                details="Current task-bound ability approval was missing, expired, revoked, or invalid before provider invocation.",
                facts={
                    "task_id": str(task.id),
                    "ability_id": manifest.ability_id,
                    "action": manifest.action_name,
                    "manifest_fingerprint": snapshot["manifest_fingerprint"],
                    "approval_required": True,
                    "reason_code": "human_approval_missing_or_invalid",
                    "enforcement_boundary": "pre_provider_invocation",
                    "mission_reference_status": "persisted" if persisted_mission_id is not None else "unverified",
                    "original_mission_id": str(task.mission_id) if task.mission_id is not None else None,
                },
                causation_id=str(task.id),
                correlation_id=str(persisted_mission_id) if persisted_mission_id is not None else None,
            )
            session.commit()
        except SQLAlchemyError as exc:
            rollback = getattr(session, "rollback", None)
            if callable(rollback):
                rollback()
            raise ToolRuntimeAuthorityError(
                "tool.invoke ability-governance denial audit is unavailable; provider execution remains blocked"
            ) from exc
