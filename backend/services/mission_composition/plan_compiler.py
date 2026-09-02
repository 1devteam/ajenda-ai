"""Compile composition selections into plan steps and task-graph preview.

Does not materialize ExecutionTasks or queue work.
"""

from __future__ import annotations

from typing import Any

from backend.services.mission_composition.action_inputs import build_action_input
from backend.services.mission_composition.contracts import (
    AbilitySelection,
    BusinessJob,
    JobAssignment,
    MissionIntent,
    PlannedStepPreview,
)
from backend.services.mission_composition.job_catalog import BUSINESS_JOBS_BY_KEY
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import SideEffectClass


def _slug(action: str) -> str:
    return action.replace(".", "-")


def _resolved_dependency_job_keys(job: BusinessJob, *, selected_keys: set[str]) -> list[str]:
    """Resolve hard + typed dependencies into job keys present in this composition.

    Catalog entries may leave ``depends_on_jobs`` empty when using conditional
    ``dependencies``. When the dep job was expanded into the same plan, wire an
    edge so downstream steps still bind upstream outputs.
    """

    if job.depends_on_jobs:
        return [key for key in job.depends_on_jobs if key in selected_keys]
    keys: list[str] = []
    for dep in job.dependencies:
        if dep.job_key in selected_keys and dep.job_key not in keys:
            keys.append(dep.job_key)
    return keys


def _binding_input_path(*, action_name: str, output_name: str) -> str | None:
    """Map upstream job products onto fields the downstream input model accepts.

    Returns None when the binding should be omitted (e.g. introduction_drafts → gtm.email_send
    cannot land on a forbidden ``prospects`` field).
    """
    if action_name in {
        "sales.qualify",
        "sales.score_lead",
        "gtm.lead_enrich",
        "gtm.email_draft",
        "sales.draft_followup",
        "research.observe_contacts",
    }:
        return "$.input.prospects"
    if action_name == "research.synthesize_report":
        return "$.input.prospects"
    if action_name == "decision.recommend_next_action":
        if output_name == "observed_contacts":
            return "$.input.context.observed_contacts"
        if output_name == "retrieved_knowledge":
            return "$.input.context.retrieved_knowledge"
        return "$.input.context.upstream"
    if action_name == "knowledge.retrieve_current":
        return None
    if action_name in {"record.write", "sales.log_activity"}:
        return f"$.input.data.{output_name}"
    if action_name in {"gtm.crm_upsert", "gtm.social_publish"}:
        if output_name in {
            "prospect_candidates",
            "qualified_prospects",
            "enriched_prospects",
            "researched_prospects",
        }:
            return f"$.input.context.{output_name}"
        return "$.input.context.upstream"
    if action_name == "gtm.email_send":
        # GtmEmailSendInput forbids extras; carry draft/world-state only under context.
        if output_name in {"introduction_drafts", "enriched_prospects", "qualified_prospects", "prospect_candidates"}:
            return f"$.input.context.{output_name}"
        return "$.input.context.upstream"
    # Default: keep world-state under context for unknown actions with forbid-extra schemas.
    return f"$.input.context.{output_name}"


def compile_planned_steps(
    selections: list[AbilitySelection],
    *,
    intent: MissionIntent | None = None,
) -> list[PlannedStepPreview]:
    """Build dependency-aware planned steps from ready selected abilities."""

    ready = [item for item in selections if item.selection_status == "selected" and item.readiness == "ready"]
    selected_keys = {item.job_key for item in ready}
    step_by_job: dict[str, PlannedStepPreview] = {}
    steps: list[PlannedStepPreview] = []

    for index, selection in enumerate(ready, start=1):
        job = BUSINESS_JOBS_BY_KEY.get(selection.job_key)
        produced = job.produced_outputs[0] if job and job.produced_outputs else f"{selection.action_name}_result"
        depends_on: list[str] = []
        input_bindings: list[dict[str, str]] = []
        if job is not None:
            for dep_job in _resolved_dependency_job_keys(job, selected_keys=selected_keys):
                dep_step = step_by_job.get(dep_job)
                if dep_step is None:
                    continue
                depends_on.append(dep_step.step_key)
                dep_job_spec = BUSINESS_JOBS_BY_KEY.get(dep_job)
                output_name = (
                    dep_job_spec.produced_outputs[0] if dep_job_spec and dep_job_spec.produced_outputs else "result"
                )
                input_path = _binding_input_path(action_name=selection.action_name, output_name=output_name)
                if input_path is None:
                    continue
                input_bindings.append(
                    {
                        "from_step": dep_step.step_key,
                        "output_path": f"$.{output_name}",
                        "to_step": f"ability-{_slug(selection.action_name)}",
                        "input_path": input_path,
                    }
                )

        tool_input: dict[str, Any] = {}
        if intent is not None:
            tool_input = build_action_input(action_name=selection.action_name, intent=intent)
            definition = get_default_action_registry().get(selection.action_name)
            if definition.input_model is not None:
                # Validate the same payload shape the runtime registry will
                # enforce. This prevents a vertical handoff from reaching graph
                # materialization with an input contract that can never run.
                definition.input_model.model_validate(tool_input)

        step = PlannedStepPreview(
            step_key=f"ability-{_slug(selection.action_name)}",
            sequence=index,
            job_key=selection.job_key,
            action_name=selection.action_name,
            title=job.display_name if job else selection.action_name,
            description=selection.selection_reason,
            depends_on=depends_on,
            output_contract=produced,
            input_bindings=input_bindings,
            tool_input=tool_input,
            credential_reference=(
                dict(selection.credential_reference) if isinstance(selection.credential_reference, dict) else None
            ),
        )
        steps.append(step)
        step_by_job[selection.job_key] = step

    # Re-number sequences after dependency-preserving order (already catalog-sorted upstream).
    for index, step in enumerate(steps, start=1):
        steps[index - 1] = step.model_copy(update={"sequence": index})
    return steps


def compile_job_assignments(selections: list[AbilitySelection]) -> list[JobAssignment]:
    assignments: list[JobAssignment] = []
    seen: set[str] = set()
    selected_keys = {
        item.job_key for item in selections if item.selection_status == "selected" and item.readiness == "ready"
    }
    for selection in selections:
        if selection.job_key in seen:
            continue
        if selection.selection_status != "selected" or selection.readiness != "ready":
            continue
        job = BUSINESS_JOBS_BY_KEY.get(selection.job_key)
        dep_keys = _resolved_dependency_job_keys(job, selected_keys=selected_keys) if job else []
        assignments.append(
            JobAssignment(
                job_key=selection.job_key,
                vertical_key=selection.vertical_role,
                display_name=job.display_name if job else selection.job_key,
                depends_on_jobs=dep_keys,
            )
        )
        seen.add(selection.job_key)
    return assignments


def _side_effect_has_effect(side_effect_class: str) -> bool:
    try:
        return SideEffectClass(side_effect_class).has_side_effect
    except ValueError:
        return side_effect_class in {
            "internal_write",
            "external_write",
            "external_send",
            "external_publish",
        }


def compile_task_graph_preview(
    steps: list[PlannedStepPreview],
    *,
    selections: list[AbilitySelection] | None = None,
) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for step in steps:
        # Same naming as mission_bridge_runtime_authority so confirm → execute
        # provisions against the graph without renaming nodes.
        capability_name = f"bridge_{step.action_name.replace('.', '_')}"
        input_contract: dict[str, Any] = {
            "tool_invocation": {
                "schema_version": 1,
                "action": step.action_name,
                "input": dict(step.tool_input),
            }
        }
        if isinstance(step.credential_reference, dict):
            input_contract["credential_reference"] = dict(step.credential_reference)
        # Approval authority is issued only against a persisted, tenant-owned
        # task during human review, never while compiling this graph.
        nodes.append(
            {
                "node_key": step.step_key,
                "key": step.step_key,
                "title": step.title,
                "description": step.description,
                "capability_reference": {
                    "capability_id": None,
                    "name": capability_name,
                    "version": "1.0.0",
                    "purpose": f"Composition-selected ability {step.action_name}.",
                },
                "input_contract": input_contract,
                "output_contract": {"artifact": step.output_contract},
                "metadata": {
                    "sequence": step.sequence,
                    "action": step.action_name,
                    "job_key": step.job_key,
                    "selected_by": "mission_composition_engine",
                    # Runtime binder (ToolRuntimeAuthority) consumes these under lease.
                    "input_bindings": list(step.input_bindings),
                    "output_contract": step.output_contract,
                },
            }
        )
        for dep in step.depends_on:
            edges.append(
                {
                    "from_node_key": dep,
                    "to_node_key": step.step_key,
                    "dependency_type": "depends_on",
                    "metadata": {"description": "Compiled from business job dependencies."},
                }
            )

    return {
        "schema_version": 1,
        "graph_status": "draft",
        "nodes": nodes,
        "edges": edges,
        "metadata": {
            "generated_by": "mission_composition_engine",
            "operator_notes": "Preview only — not admitted to runtime.",
        },
    }


def compile_plan_payload(
    *,
    objective: str,
    steps: list[PlannedStepPreview],
    success_criteria: list[str],
    constraints: list[str],
) -> dict[str, Any]:
    """Payload compatible with MissionPlanCreate / build_mission_plan_contract_metadata."""

    planned_steps: list[dict[str, Any]] = []
    key_to_sequence = {step.step_key: step.sequence for step in steps}
    for step in steps:
        depends_on = [key_to_sequence[dep] for dep in step.depends_on if dep in key_to_sequence]
        planned_steps.append(
            {
                "sequence": step.sequence,
                "title": step.title,
                "description": step.description,
                "depends_on": depends_on,
                "expected_output": step.output_contract,
                "metadata": {
                    "action": step.action_name,
                    "job_key": step.job_key,
                    "selected_by": "mission_composition_engine",
                    "input_bindings": step.input_bindings,
                    "tool_input": step.tool_input,
                },
            }
        )

    return {
        "objectives": [objective],
        "constraints": constraints or ["Operate only within mission composition allowed_actions envelope."],
        "assumptions": [
            "Composition engine selected abilities; runtime admission remains explicit.",
            "Missing external connections are reported and not simulated.",
        ],
        "acceptance_criteria": success_criteria or ["Each planned ability step produces governed evidence."],
        "planned_steps": planned_steps,
        "risk_notes": [
            "External side effects require charter allowance, credentials, and runtime authority.",
            "Draft-only missions must not include gtm.email_send.",
        ],
    }
