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
    if action_name in {"sales.qualify", "sales.score_lead"} and output_name == "observed_contacts":
        return "$.input.context.observed_contacts"
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
    if action_name in {"vertical.finance.prepare_reconciliation", "vertical.finance.prepare_invoice_drafts"}:
        return "$.input.revenue_records"
    if action_name == "decision.recommend_next_action":
        if output_name == "business_profile_facts":
            return "$.input.context.business_profile_facts"
        if output_name == "observed_contacts":
            return "$.input.context.observed_contacts"
        if output_name == "retrieved_knowledge":
            return "$.input.context.retrieved_knowledge"
        return "$.input.context.upstream"
    if action_name == "knowledge.retrieve_current":
        return None
    if action_name == "record.write" and output_name in {"qualified_prospects", "observed_contacts"}:
        return f"$.input.context.{output_name}"
    if action_name == "record.write" and output_name == "enriched_prospects":
        return "$.input.context.enriched_prospects"
    if action_name == "record.write" and output_name == "prospect_candidates":
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


def _dependency_output_name(*, dependency: BusinessJob, downstream_action: str) -> str:
    """Choose the downstream-facing product when a job declares multiple outputs."""

    if dependency.job_key == "research.observe_sources" and downstream_action in {
        "sales.qualify",
        "sales.score_lead",
    }:
        # Observation is the terminal public-research boundary. Downstream
        # qualification must consume verified identities, while contacts are
        # supplementary evidence and must not stand in for companies.
        return "verified_prospect_candidates"
    if dependency.job_key == "research.observe_sources" and downstream_action == "gtm.crm_upsert":
        return "verified_prospect_candidates"
    if dependency.job_key == "research.observe_sources" and downstream_action == "record.write":
        return "observed_contacts"
    if dependency.job_key == "crm.read_records" and downstream_action in {
        "research.observe_contacts",
        "sales.qualify",
        "sales.score_lead",
        "gtm.lead_enrich",
        "gtm.email_draft",
        "sales.draft_followup",
    }:
        return "crm_records"
    return dependency.produced_outputs[0] if dependency.produced_outputs else "result"


def _dependency_jobs_for_selection(
    *,
    job: BusinessJob,
    selected_keys: set[str],
    intent: MissionIntent | None,
) -> list[str]:
    """Resolve catalog dependencies plus the internal CRM source edge."""

    dependencies = _resolved_dependency_job_keys(job, selected_keys=selected_keys)
    if (
        intent is not None
        and "internal_crm_source" in {str(item) for item in intent.context_requirements}
        and job.job_key
        in {
            "research.observe_sources",
            "sales.qualify_prospects",
            "gtm.enrich_contacts",
            "email.prepare_outreach",
        }
        and "crm.read_records" in selected_keys
    ):
        dependencies = ["crm.read_records", *dependencies]
    if (
        intent is not None
        and job.job_key == "crm.internal_persistence"
        and "enrich_contacts" in set(intent.requested_outcomes)
        and "gtm.enrich_contacts" in selected_keys
    ):
        # Explicit enrichment is part of the persistence payload, not an
        # unconsumed side branch. Keep the dependency conditional on the
        # requested outcome so missions that do not ask for enrichment retain
        # the smaller governed write graph.
        dependencies.append("gtm.enrich_contacts")
    return list(dict.fromkeys(dependencies))


def _order_selected_jobs(
    *,
    ready: list[AbilitySelection],
    selected_keys: set[str],
    intent: MissionIntent | None,
) -> list[AbilitySelection]:
    """Topologically order selected jobs so bindings never point downstream."""

    by_key = {selection.job_key: selection for selection in ready}
    ordered: list[AbilitySelection] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(job_key: str) -> None:
        if job_key in visited:
            return
        if job_key in visiting:
            raise ValueError(f"mission composition job dependency cycle at {job_key}")
        selection = by_key.get(job_key)
        if selection is None:
            return
        visiting.add(job_key)
        job = BUSINESS_JOBS_BY_KEY.get(job_key)
        if job is not None:
            for dependency in _dependency_jobs_for_selection(
                job=job,
                selected_keys=selected_keys,
                intent=intent,
            ):
                visit(dependency)
        visiting.remove(job_key)
        visited.add(job_key)
        ordered.append(selection)

    for selection in ready:
        visit(selection.job_key)
    return ordered


def compile_planned_steps(
    selections: list[AbilitySelection],
    *,
    intent: MissionIntent | None = None,
) -> list[PlannedStepPreview]:
    """Build dependency-aware planned steps from ready selected abilities."""

    ready = [item for item in selections if item.selection_status == "selected" and item.readiness == "ready"]
    selected_keys = {item.job_key for item in ready}
    ready = _order_selected_jobs(ready=ready, selected_keys=selected_keys, intent=intent)
    step_by_job: dict[str, PlannedStepPreview] = {}
    steps: list[PlannedStepPreview] = []

    for index, selection in enumerate(ready, start=1):
        job = BUSINESS_JOBS_BY_KEY.get(selection.job_key)
        produced = job.produced_outputs[0] if job and job.produced_outputs else f"{selection.action_name}_result"
        depends_on: list[str] = []
        input_bindings: list[dict[str, str]] = []
        if job is not None:
            for dep_job in _dependency_jobs_for_selection(job=job, selected_keys=selected_keys, intent=intent):
                dep_step = step_by_job.get(dep_job)
                if dep_step is None:
                    continue
                depends_on.append(dep_step.step_key)
                dep_job_spec = BUSINESS_JOBS_BY_KEY.get(dep_job)
                if (
                    dep_job == "research.discover_prospects"
                    and selection.action_name in {"sales.qualify", "sales.score_lead"}
                    and "research.observe_sources" in selected_keys
                ):
                    # Raw discovery is an intermediate artifact. Once the
                    # observer is in the graph, bind only its verified terminal
                    # artifact so qualification cannot score unresolved hits.
                    continue
                if (
                    dep_job == "research.discover_prospects"
                    and selection.action_name in {"gtm.email_draft", "sales.draft_followup"}
                    and any(
                        key in selected_keys
                        for key in {"sales.qualify_prospects", "gtm.lead_enrich", "research.observe_sources"}
                    )
                ):
                    # Drafts consume the qualified/enriched terminal world-state;
                    # raw discovery is retained only as intermediate evidence.
                    continue
                output_name = (
                    _dependency_output_name(dependency=dep_job_spec, downstream_action=selection.action_name)
                    if dep_job_spec
                    else "result"
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
                if dep_job == "research.observe_sources" and selection.action_name in {
                    "sales.qualify",
                    "sales.score_lead",
                }:
                    input_bindings.append(
                        {
                            "from_step": dep_step.step_key,
                            "output_path": "$.observed_contacts",
                            "to_step": f"ability-{_slug(selection.action_name)}",
                            "input_path": "$.input.context.observed_contacts",
                        }
                    )

        tool_input: dict[str, Any] = {}
        compile_gap: str | None = None
        if intent is not None:
            try:
                tool_input = build_action_input(
                    action_name=selection.action_name,
                    intent=intent,
                    vertical_role=selection.vertical_role,
                )
                definition = get_default_action_registry().get(selection.action_name)
                if definition.input_model is not None:
                    # Validate the same payload shape the runtime registry will
                    # enforce. This prevents a vertical handoff from reaching graph
                    # materialization with an input contract that can never run.
                    definition.input_model.model_validate(tool_input)
            except (ValueError, TypeError) as exc:
                compile_gap = str(exc)[:500]
                tool_input = {}

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
            compile_gap=compile_gap,
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
        # Public discovery is a source stage when the composition also selected
        # identity observation. Its raw hits must be handed to that downstream
        # verifier even when none is verified yet; they are never a completed
        # deliverable. The final typed artifact remains fail-closed.
        intermediate_public_discovery = (
            step.action_name == "web.research"
            and bool(step.tool_input.get("include_public_search"))
            and any(
                item.action_name == "research.observe_contacts"
                and any(binding.get("from_step") == step.step_key for binding in item.input_bindings)
                for item in steps
            )
        )
        output_contract: dict[str, Any] = {"artifact": step.output_contract}
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
                "output_contract": output_contract,
                "metadata": {
                    "sequence": step.sequence,
                    "action": step.action_name,
                    "job_key": step.job_key,
                    "selected_by": "mission_composition_engine",
                    # Runtime binder (ToolRuntimeAuthority) consumes these under lease.
                    "input_bindings": list(step.input_bindings),
                    "output_contract": step.output_contract,
                    "materialization_role": "intermediate" if intermediate_public_discovery else "terminal",
                    "allow_empty": intermediate_public_discovery,
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
