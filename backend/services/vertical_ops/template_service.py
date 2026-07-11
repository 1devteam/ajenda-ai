"""Apply vertical mission templates onto the existing mission/runtime spine.

Authority classes:
- build_* methods: declarative / pure (no DB side effects)
- apply_to_mission: governed_mutation (mission metadata + planned ExecutionTask rows
  for Phase B; plan/graph only for Phase C)
- queue_planned_tasks: runtime admission via existing ExecutionCoordinator only
  (Phase B). Phase C fails closed — no queue until providers prove safe.

Forbidden:
- parallel agent_swarm coordinator
- Celery / Beat
- direct TaskDispatcher or WorkerLoop calls from this package
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy.orm import Session

from backend.domain.capability import Capability
from backend.domain.capability_adapter import CapabilityAdapter
from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import (
    MISSION_PLAN_CONTRACT_SCHEMA_VERSION,
    MISSION_TASK_GRAPH_METADATA_KEY,
    Mission,
    build_mission_plan_contract_metadata,
    build_mission_task_graph_contract_metadata,
)
from backend.queue.base import QueueAdapter
from backend.services.abilities.catalog import ABILITY_MANIFESTS_BY_ACTION
from backend.services.abilities.manifest import AbilityRiskLevel
from backend.services.abilities.vertical_role_catalog import RoleBindingStatus, get_vertical_role
from backend.services.execution_coordinator import CoordinationResult, ExecutionCoordinator
from backend.services.tools.schemas import CredentialReference, SideEffectClass
from backend.services.vertical_ops.plan_templates import (
    VerticalMissionTemplate,
    VerticalTemplateStep,
    get_vertical_mission_template,
    template_step_side_effect,
)

VERTICAL_TEMPLATE_METADATA_KEY = "vertical_ops_template"
VERTICAL_PLAN_CONTRACT_METADATA_KEY = "mission_plan_contract"


@dataclass(frozen=True, slots=True)
class PlannedVerticalTaskSpec:
    """Planned task payload ready for ExecutionTask persistence (not yet queued)."""

    step_key: str
    action_name: str
    title: str
    description: str
    compliance_category: str
    jurisdiction: str
    requires_human_review: bool
    metadata_json: dict[str, Any]
    dependency_step_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VerticalTemplateBundle:
    """Declarative planning bundle produced from a vertical template."""

    template_id: str
    role_key: str
    pack_id: str
    pack_version: str
    objective: str
    plan_contract: dict[str, Any]
    task_graph: dict[str, Any]
    planned_tasks: tuple[PlannedVerticalTaskSpec, ...]
    phase: Literal["B", "C"]
    allows_runtime_queue: bool
    authority_class: Literal["declarative"] = "declarative"
    grants_execution_authority: Literal[False] = False


@dataclass(frozen=True, slots=True)
class VerticalTemplateApplyResult:
    """Result of attaching a template to a mission and creating planned tasks."""

    mission_id: uuid.UUID
    template_id: str
    created_task_ids: tuple[uuid.UUID, ...]
    plan_contract: dict[str, Any]
    task_graph: dict[str, Any]
    authority_class: Literal["governed_mutation"] = "governed_mutation"
    enqueued: Literal[False] = False


@dataclass(frozen=True, slots=True)
class VerticalTemplateQueueResult:
    """Result of queue admission via ExecutionCoordinator."""

    results: tuple[CoordinationResult, ...]
    queued_task_ids: tuple[uuid.UUID, ...]
    blocked_task_ids: tuple[uuid.UUID, ...]
    authority_class: Literal["runtime_authoritative"] = "runtime_authoritative"


def _adapter_side_effect_classification(side_effect_class: SideEffectClass) -> str:
    if side_effect_class == SideEffectClass.NONE:
        return "none"
    if side_effect_class == SideEffectClass.INTERNAL_READ:
        return "read_only"
    if side_effect_class == SideEffectClass.INTERNAL_WRITE:
        return "non_idempotent_write"
    if side_effect_class in {
        SideEffectClass.EXTERNAL_READ,
        SideEffectClass.EXTERNAL_WRITE,
        SideEffectClass.EXTERNAL_SEND,
        SideEffectClass.EXTERNAL_PUBLISH,
    }:
        return side_effect_class.value
    return "external_side_effect"


def _requires_runtime_authority(side_effect_class: SideEffectClass) -> bool:
    return side_effect_class.has_side_effect or side_effect_class.value.startswith("external_")


class VerticalOpsTemplateService:
    """Build and apply vertical templates on the native mission spine."""

    def build_bundle(
        self,
        *,
        template_id: str,
        step_inputs: dict[str, dict[str, Any]] | None = None,
        selected_step_keys: tuple[str, ...] | list[str] | None = None,
        objective: str | None = None,
        approved_by: str = "vertical-ops-template",
        approval_reason: str = "Vertical ops template application.",
        idempotency_keys: Mapping[str, str] | None = None,
        credential_references: Mapping[str, CredentialReference | dict[str, Any]] | None = None,
        jurisdiction: str | None = None,
    ) -> VerticalTemplateBundle:
        template = get_vertical_mission_template(template_id)
        role = get_vertical_role(template.role_key)
        steps = template.selected_steps(selected_step_keys)
        step_inputs = step_inputs or {}
        idempotency_keys = idempotency_keys or {}
        credential_references = credential_references or {}
        resolved_jurisdiction = (jurisdiction or role.default_jurisdiction).strip()

        # Runtime-queueable steps fail closed on missing credentials/idempotency
        # before any ExecutionTask is created or admitted. Phase C plan-only
        # templates skip this — they never enqueue.
        if template.allows_runtime_queue:
            for step in steps:
                binding = template.resolve_binding(step.action_name)
                side_effect = template_step_side_effect(step.action_name, role_key=template.role_key)
                has_credential = step.step_key in credential_references or step.action_name in credential_references
                if binding.credential_required and not has_credential:
                    raise ValueError(f"step {step.step_key} ({step.action_name}) requires credential_references entry")
                if side_effect in {
                    SideEffectClass.EXTERNAL_WRITE,
                    SideEffectClass.EXTERNAL_SEND,
                    SideEffectClass.EXTERNAL_PUBLISH,
                }:
                    key = idempotency_keys.get(step.step_key) or idempotency_keys.get(step.action_name)
                    if not key:
                        raise ValueError(f"step {step.step_key} ({step.action_name}) requires idempotency_keys entry")
                    # External mutating actions also require credentials at admission.
                    if not has_credential:
                        raise ValueError(
                            f"step {step.step_key} ({step.action_name}) requires credential_references entry"
                        )

        step_key_to_sequence = {step.step_key: index for index, step in enumerate(steps, start=1)}
        planned_steps: list[dict[str, Any]] = []
        for step in steps:
            depends_on_sequences = [step_key_to_sequence[dep] for dep in step.depends_on if dep in step_key_to_sequence]
            binding = template.resolve_binding(step.action_name)
            planned_steps.append(
                {
                    "sequence": step_key_to_sequence[step.step_key],
                    "title": step.title,
                    "description": step.description,
                    "depends_on": depends_on_sequences,
                    "expected_output": f"evidence for {step.action_name}",
                    "metadata": {
                        "step_key": step.step_key,
                        "action_name": step.action_name,
                        "template_id": template.template_id,
                        "role_key": template.role_key,
                        "binding_status": binding.binding_status.value,
                        "phase": template.phase,
                        "allows_runtime_queue": template.allows_runtime_queue,
                    },
                }
            )

        plan_contract = build_mission_plan_contract_metadata(
            objectives=[objective or template.objective_template],
            constraints=[
                f"role_key={template.role_key}",
                f"pack_id={template.pack_id}",
                f"template_id={template.template_id}",
                f"phase={template.phase}",
                f"allows_runtime_queue={template.allows_runtime_queue}",
                "authority=declarative_template",
            ],
            assumptions=[
                "Runtime execution uses existing ExecutionCoordinator and tool.invoke spine.",
                "Template does not grant execution authority by itself.",
                (
                    "Phase C plan-only templates cannot queue until providers prove safe."
                    if not template.allows_runtime_queue
                    else "Phase B steps may queue through ExecutionCoordinator only."
                ),
            ],
            acceptance_criteria=list(role.evidence_expectations),
            planned_steps=planned_steps,
            risk_notes=[
                f"role_risk={role.risk_level.value}",
                f"requires_human_review={role.requires_human_review}",
                f"compliance_category={role.compliance_category}",
            ],
        )

        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        for step in steps:
            binding = template.resolve_binding(step.action_name)
            nodes.append(
                {
                    "node_key": step.step_key,
                    "key": step.step_key,
                    "title": step.title,
                    "description": step.description,
                    "capability_reference": {
                        "capability_id": None,
                        "name": binding.capability_name,
                        "version": binding.capability_version,
                        "purpose": f"Vertical template action {step.action_name}",
                    },
                    "capability_references": [
                        {
                            "capability_id": None,
                            "name": binding.capability_name,
                            "version": binding.capability_version,
                            "purpose": f"Vertical template action {step.action_name}",
                        }
                    ],
                    "input_contract": {
                        "action_name": step.action_name,
                        "step_key": step.step_key,
                        "tool_input": dict(step_inputs.get(step.step_key) or step_inputs.get(step.action_name) or {}),
                    },
                    "output_contract": {
                        "evidence_expectations": list(binding.evidence_expectations),
                    },
                    "metadata": {
                        "vertical_role_key": template.role_key,
                        "action_name": step.action_name,
                        "side_effect_class": binding.side_effect_class.value,
                        "risk_level": binding.risk_level.value,
                        "binding_status": binding.binding_status.value,
                        "intended_task_type": "tool.invoke" if template.allows_runtime_queue else "plan_only",
                        "runtime_task_type": "tool.invoke" if template.allows_runtime_queue else "plan_only",
                        "allows_runtime_queue": template.allows_runtime_queue,
                    },
                }
            )
            for dep in step.depends_on:
                edges.append(
                    {
                        "from_node_key": dep,
                        "to_node_key": step.step_key,
                        "dependency_type": "depends_on",
                        "metadata": {},
                    }
                )

        task_graph = build_mission_task_graph_contract_metadata(
            nodes=nodes,
            edges=edges,
            metadata={
                "template_id": template.template_id,
                "role_key": template.role_key,
                "pack_id": template.pack_id,
                "pack_version": template.pack_version,
                "phase": template.phase,
                "allows_runtime_queue": template.allows_runtime_queue,
                "source": f"vertical_ops_phase_{template.phase.lower()}",
            },
        )

        planned_tasks: list[PlannedVerticalTaskSpec] = []
        if template.allows_runtime_queue:
            for step in steps:
                binding = template.resolve_binding(step.action_name)
                if binding.binding_status is not RoleBindingStatus.RUNTIME_BOUND:
                    continue
                planned_tasks.append(
                    self._build_planned_task_spec(
                        template=template,
                        step=step,
                        step_inputs=step_inputs,
                        approved_by=approved_by,
                        approval_reason=approval_reason,
                        idempotency_keys=idempotency_keys,
                        credential_references=credential_references,
                        jurisdiction=resolved_jurisdiction,
                    )
                )

        return VerticalTemplateBundle(
            template_id=template.template_id,
            role_key=template.role_key,
            pack_id=template.pack_id,
            pack_version=template.pack_version,
            objective=objective or template.objective_template,
            plan_contract=plan_contract,
            task_graph=task_graph,
            planned_tasks=tuple(planned_tasks),
            phase=template.phase,
            allows_runtime_queue=template.allows_runtime_queue,
        )

    def apply_to_mission(
        self,
        *,
        session: Session,
        mission: Mission,
        template_id: str,
        step_inputs: dict[str, dict[str, Any]] | None = None,
        selected_step_keys: tuple[str, ...] | list[str] | None = None,
        objective: str | None = None,
        approved_by: str = "vertical-ops-template",
        approval_reason: str = "Vertical ops Phase B template application.",
        idempotency_keys: dict[str, str] | None = None,
        credential_references: Mapping[str, CredentialReference | dict[str, Any]] | None = None,
        jurisdiction: str | None = None,
        create_runtime_authority: bool = True,
    ) -> VerticalTemplateApplyResult:
        """Attach plan/graph metadata and create planned ExecutionTask rows.

        Does not enqueue. Caller must use queue_planned_tasks → ExecutionCoordinator.
        """
        if not mission.tenant_id or not str(mission.tenant_id).strip():
            raise ValueError("mission.tenant_id is required")

        bundle = self.build_bundle(
            template_id=template_id,
            step_inputs=step_inputs,
            selected_step_keys=selected_step_keys,
            objective=objective,
            approved_by=approved_by,
            approval_reason=approval_reason,
            idempotency_keys=idempotency_keys,
            credential_references=credential_references,
            jurisdiction=jurisdiction,
        )
        role = get_vertical_role(bundle.role_key)

        metadata = dict(mission.metadata_json or {})
        metadata[VERTICAL_PLAN_CONTRACT_METADATA_KEY] = bundle.plan_contract
        metadata[MISSION_TASK_GRAPH_METADATA_KEY] = bundle.task_graph
        selected_keys = [task.step_key for task in bundle.planned_tasks]
        if not selected_keys:
            # Phase C plan-only: no runtime tasks; still record graph node keys.
            selected_keys = [
                str(node.get("node_key"))
                for node in (bundle.task_graph.get("nodes") or [])
                if isinstance(node, dict) and isinstance(node.get("node_key"), str)
            ]
        metadata[VERTICAL_TEMPLATE_METADATA_KEY] = {
            "schema_version": 1,
            "template_id": bundle.template_id,
            "role_key": bundle.role_key,
            "pack_id": bundle.pack_id,
            "pack_version": bundle.pack_version,
            "phase": bundle.phase,
            "allows_runtime_queue": bundle.allows_runtime_queue,
            "applied_at": datetime.now(UTC).isoformat(),
            "authority_class": "governed_mutation",
            "grants_execution_authority": False,
            "plan_contract_schema_version": MISSION_PLAN_CONTRACT_SCHEMA_VERSION,
            "selected_step_keys": selected_keys,
        }
        mission.metadata_json = metadata
        if objective or not mission.objective:
            mission.objective = bundle.objective
        # Align mission compliance defaults with role when still operational baseline.
        if getattr(mission, "compliance_category", None) in (None, "", "operational"):
            if role.compliance_category != "operational":
                mission.compliance_category = role.compliance_category
        if jurisdiction:
            mission.jurisdiction = jurisdiction.strip()
        elif not getattr(mission, "jurisdiction", None):
            mission.jurisdiction = role.default_jurisdiction

        session.add(mission)
        session.flush()

        created_ids: list[uuid.UUID] = []
        for planned in bundle.planned_tasks:
            metadata_json = dict(planned.metadata_json)
            side_effect = SideEffectClass(
                metadata_json.get("side_effect_class") or template_step_side_effect(planned.action_name).value
            )
            if create_runtime_authority and _requires_runtime_authority(side_effect):
                capability, adapter = self._ensure_runtime_authority(
                    session=session,
                    tenant_id=str(mission.tenant_id),
                    action_name=planned.action_name,
                    side_effect_class=side_effect,
                    approved_by=approved_by,
                )
                metadata_json["capability_reference"] = {"capability_id": str(capability.id)}
                metadata_json["adapter_reference"] = {"adapter_id": str(adapter.id)}

            task = ExecutionTask(
                tenant_id=str(mission.tenant_id),
                mission_id=mission.id,
                title=planned.title,
                description=planned.description,
                status=ExecutionTaskState.PLANNED.value,
                metadata_json=metadata_json,
                compliance_category=planned.compliance_category,
                jurisdiction=planned.jurisdiction,
                requires_human_review=planned.requires_human_review,
            )
            session.add(task)
            session.flush()
            created_ids.append(task.id)

        # Persist applied task ids for later queue endpoints (still not an execution grant).
        template_meta = dict(mission.metadata_json.get(VERTICAL_TEMPLATE_METADATA_KEY) or {})
        template_meta["created_task_ids"] = [str(task_id) for task_id in created_ids]
        template_meta["created_task_count"] = len(created_ids)
        mission.metadata_json = {
            **dict(mission.metadata_json or {}),
            VERTICAL_TEMPLATE_METADATA_KEY: template_meta,
        }
        session.add(mission)
        session.flush()

        return VerticalTemplateApplyResult(
            mission_id=mission.id,
            template_id=bundle.template_id,
            created_task_ids=tuple(created_ids),
            plan_contract=bundle.plan_contract,
            task_graph=bundle.task_graph,
        )

    def ensure_runtime_queue_allowed(self, *, template_id: str) -> None:
        """Fail closed when a template is plan-only (Phase C)."""

        template = get_vertical_mission_template(template_id)
        if not template.allows_runtime_queue:
            raise ValueError(
                f"template {template_id!r} is plan-only (phase {template.phase}); "
                "runtime queue is disabled until providers, credentials, idempotency, "
                "and human-review proof land (ADR-0007 Phase C)"
            )

    def queue_planned_tasks(
        self,
        *,
        session: Session,
        queue: QueueAdapter,
        tenant_id: str,
        task_ids: tuple[uuid.UUID, ...] | list[uuid.UUID],
        template_id: str | None = None,
    ) -> VerticalTemplateQueueResult:
        """Admit planned tasks through the existing ExecutionCoordinator only."""

        if not tenant_id.strip():
            raise ValueError("tenant_id is required")
        if not task_ids:
            raise ValueError("task_ids is required")
        if template_id is not None:
            self.ensure_runtime_queue_allowed(template_id=template_id)

        coordinator = ExecutionCoordinator(session, queue)
        results: list[CoordinationResult] = []
        queued: list[uuid.UUID] = []
        blocked: list[uuid.UUID] = []
        for task_id in task_ids:
            result = coordinator.queue_task(tenant_id=tenant_id, task_id=task_id)
            results.append(result)
            if result.ok:
                queued.append(task_id)
            else:
                blocked.append(task_id)
        return VerticalTemplateQueueResult(
            results=tuple(results),
            queued_task_ids=tuple(queued),
            blocked_task_ids=tuple(blocked),
        )

    def apply_and_queue(
        self,
        *,
        session: Session,
        queue: QueueAdapter,
        mission: Mission,
        template_id: str,
        step_inputs: dict[str, dict[str, Any]] | None = None,
        selected_step_keys: tuple[str, ...] | list[str] | None = None,
        objective: str | None = None,
        approved_by: str = "vertical-ops-template",
        approval_reason: str = "Vertical ops Phase B template application.",
        idempotency_keys: dict[str, str] | None = None,
        credential_references: Mapping[str, CredentialReference | dict[str, Any]] | None = None,
        jurisdiction: str | None = None,
        create_runtime_authority: bool = True,
    ) -> tuple[VerticalTemplateApplyResult, VerticalTemplateQueueResult]:
        """Convenience: apply template then queue via ExecutionCoordinator."""

        self.ensure_runtime_queue_allowed(template_id=template_id)
        applied = self.apply_to_mission(
            session=session,
            mission=mission,
            template_id=template_id,
            step_inputs=step_inputs,
            selected_step_keys=selected_step_keys,
            objective=objective,
            approved_by=approved_by,
            approval_reason=approval_reason,
            idempotency_keys=idempotency_keys,
            credential_references=credential_references,
            jurisdiction=jurisdiction,
            create_runtime_authority=create_runtime_authority,
        )
        if not applied.created_task_ids:
            raise ValueError(f"template {template_id!r} produced no runtime tasks to queue")
        queued = self.queue_planned_tasks(
            session=session,
            queue=queue,
            tenant_id=str(mission.tenant_id),
            task_ids=applied.created_task_ids,
            template_id=template_id,
        )
        return applied, queued

    def _build_planned_task_spec(
        self,
        *,
        template: VerticalMissionTemplate,
        step: VerticalTemplateStep,
        step_inputs: dict[str, dict[str, Any]],
        approved_by: str,
        approval_reason: str,
        idempotency_keys: Mapping[str, str],
        credential_references: Mapping[str, CredentialReference | dict[str, Any]],
        jurisdiction: str,
    ) -> PlannedVerticalTaskSpec:
        role = get_vertical_role(template.role_key)
        binding = template.resolve_binding(step.action_name)
        if binding.binding_status is not RoleBindingStatus.RUNTIME_BOUND:
            raise ValueError(f"cannot materialize catalog_only action {step.action_name!r} as ExecutionTask")
        manifest = ABILITY_MANIFESTS_BY_ACTION[step.action_name]
        side_effect = manifest.side_effect_class
        input_payload = dict(step_inputs.get(step.step_key) or step_inputs.get(step.action_name) or {})

        tool_invocation: dict[str, Any] = {
            "schema_version": 1,
            "action": step.action_name,
            "input": input_payload,
            "provider": manifest.provider,
        }
        idem_key = idempotency_keys.get(step.step_key) or idempotency_keys.get(step.action_name)
        if idem_key:
            tool_invocation["idempotency_key"] = idem_key.strip()

        cred = credential_references.get(step.step_key) or credential_references.get(step.action_name)
        credential_payload: dict[str, Any] | None = None
        if cred is not None:
            if isinstance(cred, CredentialReference):
                credential_payload = cred.model_dump(mode="json")
            else:
                credential_payload = dict(cred)
            tool_invocation["credential_reference"] = credential_payload

        requires_human_review = bool(
            role.requires_human_review
            or binding.requires_human_review
            or binding.risk_level in {AbilityRiskLevel.HIGH, AbilityRiskLevel.CRITICAL}
            or side_effect
            in {
                SideEffectClass.EXTERNAL_SEND,
                SideEffectClass.EXTERNAL_PUBLISH,
                SideEffectClass.EXTERNAL_WRITE,
            }
        )

        metadata_json: dict[str, Any] = {
            "schema_version": 1,
            "task_type": "tool.invoke",
            "launched_by": "vertical-ops-template",
            "tool_invocation": tool_invocation,
            "side_effect_class": side_effect.value,
            "vertical_role_key": template.role_key,
            "vertical_pack_id": template.pack_id,
            "vertical_pack_version": template.pack_version,
            "template_id": template.template_id,
            "template_step_key": step.step_key,
            "dependency_step_keys": list(step.depends_on),
            "graph_node_key": step.step_key,
        }
        if credential_payload is not None:
            metadata_json["credential_reference"] = credential_payload

        if side_effect.has_side_effect:
            metadata_json["execution_constraints"] = {
                "side_effect_authorization": {
                    "schema_version": 1,
                    "allowed_actions": [step.action_name],
                    "reason": approval_reason,
                    "approved_by": approved_by,
                }
            }

        return PlannedVerticalTaskSpec(
            step_key=step.step_key,
            action_name=step.action_name,
            title=step.title,
            description=step.description,
            compliance_category=role.compliance_category,
            jurisdiction=jurisdiction,
            requires_human_review=requires_human_review,
            metadata_json=metadata_json,
            dependency_step_keys=step.depends_on,
        )

    def _ensure_runtime_authority(
        self,
        *,
        session: Session,
        tenant_id: str,
        action_name: str,
        side_effect_class: SideEffectClass,
        approved_by: str,
    ) -> tuple[Capability, CapabilityAdapter]:
        """Create tenant-scoped declarative capability/adapter authority (same pattern as ability-runtime)."""

        suffix = uuid.uuid4().hex[:10]
        approval_required = side_effect_class in {
            SideEffectClass.EXTERNAL_WRITE,
            SideEffectClass.EXTERNAL_SEND,
            SideEffectClass.EXTERNAL_PUBLISH,
        }
        capability = Capability(
            tenant_id=tenant_id,
            name=f"vertical-{action_name}-{suffix}",
            version="1.0.0",
            description=f"Vertical ops Phase B runtime authority for {action_name}.",
            supported_task_types=["tool.invoke", action_name],
            input_schema_hints={},
            output_schema_hints={},
            required_permissions=[],
            required_tools=[action_name],
            risk_level="high" if approval_required else "medium",
            approval_requirements={
                "required": approval_required,
                "generated_by": "vertical-ops-template",
                "approved_by": approved_by,
            },
            evidence_expectations=[f"{action_name} evidence"],
            execution_constraints={},
            enabled=True,
            schema_version=1,
        )
        session.add(capability)
        session.flush()

        adapter = CapabilityAdapter(
            tenant_id=tenant_id,
            name=f"vertical-{action_name}-adapter-{suffix}",
            version="1.0.0",
            capability_id=capability.id,
            capability_name=capability.name,
            capability_version=capability.version,
            supported_task_types=["tool.invoke", action_name],
            input_contract={},
            output_contract={},
            required_permissions=[],
            required_tools=[action_name],
            execution_mode="queued",
            risk_level="high" if approval_required else "medium",
            approval_requirements={
                "required": approval_required,
                "generated_by": "vertical-ops-template",
                "approved_by": approved_by,
            },
            evidence_expectations=[f"{action_name} evidence"],
            timeout_retry_hints={},
            idempotency_expectations={},
            side_effect_classification=_adapter_side_effect_classification(side_effect_class),
            enabled=True,
            schema_version=1,
        )
        session.add(adapter)
        session.flush()
        return capability, adapter
