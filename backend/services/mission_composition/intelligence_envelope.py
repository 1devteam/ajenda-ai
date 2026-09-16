"""Build the shared intelligence handoff envelope across composition layers."""

from __future__ import annotations

import hashlib
from typing import Any

from backend.services.mission_composition.capability_resolver import intent_input_sources
from backend.services.mission_composition.contracts import (
    AbilitySelection,
    BusinessJob,
    Clarification,
    CompositionLayer,
    IntelligenceEnvelope,
    LayerGap,
    MissionIntent,
    PlannedStepPreview,
)
from backend.services.mission_composition.job_catalog import BUSINESS_JOB_CATALOG, BUSINESS_JOBS_BY_KEY

_ARTIFACT_KEYS = {output for job in BUSINESS_JOB_CATALOG for output in job.produced_outputs}


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _gap(
    *,
    layer: CompositionLayer,
    code: str,
    field: str,
    message: str,
    blocking: bool = True,
) -> LayerGap:
    return LayerGap(layer=layer, code=code, field=field, message=message[:1000], blocking=blocking)


def collect_layer_gaps(
    *,
    intent: MissionIntent,
    jobs: list[BusinessJob],
    selections: list[AbilitySelection],
    planned_steps: list[PlannedStepPreview],
    missing_connections: list[dict[str, Any]] | None = None,
    planner_provenance: dict[str, Any] | None = None,
    planner_compile_error: str | None = None,
) -> tuple[LayerGap, ...]:
    """Collect interpreter, algorithm, and planner gaps together. Never invent work."""

    gaps: list[LayerGap] = []
    job_keys = {job.job_key for job in jobs}
    produced = {output for job in jobs for output in job.produced_outputs}
    sources = intent_input_sources(intent) | produced

    if not intent.requested_outcomes:
        gaps.append(
            _gap(
                layer="interpreter",
                code="no_named_outcome",
                field="requested_outcomes",
                message=(
                    "Restate the complete mission with a concrete outcome Ajenda can name as work "
                    "(for example research, qualify, draft, read a connected system, or persist records)."
                ),
            )
        )
    for item in intent.ambiguity:
        gaps.append(
            _gap(
                layer="interpreter",
                code="restatement_required",
                field=item.field,
                message=item.question,
            )
        )
    for clause in intent.unmatched_material_clauses:
        gaps.append(
            _gap(
                layer="interpreter",
                code="unmatched_material_clause",
                field=clause.clause_id,
                message=(f"Restate the complete mission including this unmatched requirement: {clause.text}"),
            )
        )
    for contradiction in intent.contradictions:
        if contradiction.resolution_status != "unresolved":
            continue
        gaps.append(
            _gap(
                layer="interpreter",
                code="unresolved_contradiction",
                field=contradiction.field_path,
                message=(
                    "Restate the complete mission so this contradiction is resolved: "
                    f"{contradiction.first_value} vs {contradiction.second_value}."
                ),
            )
        )
    for reason in intent.interpretation_readiness_reasons:
        if reason == "restatement_required":
            continue
        gaps.append(
            _gap(
                layer="interpreter",
                code="readiness_failed",
                field="interpretation_ready",
                message=f"Interpretation is not ready ({reason}). Restate the complete mission.",
            )
        )

    supported_by_catalog = {outcome for job in BUSINESS_JOB_CATALOG for outcome in job.supported_outcomes}
    for outcome in intent.requested_outcomes:
        if outcome not in supported_by_catalog:
            gaps.append(
                _gap(
                    layer="algorithm",
                    code="outcome_has_no_job",
                    field=outcome,
                    message=(f"Restate the complete mission; Ajenda has no named job for outcome '{outcome}'."),
                )
            )
    if intent.requested_outcomes and not jobs:
        gaps.append(
            _gap(
                layer="algorithm",
                code="no_named_jobs",
                field="jobs",
                message=(
                    "Restate the complete mission so Ajenda can name at least one job. "
                    "Outcomes were understood but no catalog job could be routed."
                ),
            )
        )
    if not intent.requested_outcomes and not jobs:
        gaps.append(
            _gap(
                layer="algorithm",
                code="no_named_jobs",
                field="jobs",
                message=(
                    "Ajenda could not name any job from this instruction. Restate the complete "
                    "mission with an outcome, scope, and deliverable."
                ),
            )
        )
    for job in jobs:
        for required in job.required_inputs:
            if required not in _ARTIFACT_KEYS:
                if required == "github_owner_repo" and "github_owner_repo" not in sources:
                    gaps.append(
                        _gap(
                            layer="algorithm",
                            code="unbound_required_input",
                            field="github_owner_repo",
                            message=(
                                "Restate the complete mission with the GitHub owner/repository "
                                "(for example octocat/Hello-World). A status without that artifact "
                                "input cannot become named work."
                            ),
                        )
                    )
                if required == "target_industry_or_query" and "target_industry_or_query" not in sources:
                    gaps.append(
                        _gap(
                            layer="algorithm",
                            code="unbound_required_input",
                            field="target_scope",
                            message=(
                                "Research work is named, but target scope is missing. Restate the complete "
                                "mission with industry or company type and city/region, or competitors of a "
                                "named company. Refusing a placeholder query such as 'companies'."
                            ),
                        )
                    )
                continue
            if required in sources:
                continue
            gaps.append(
                _gap(
                    layer="algorithm",
                    code="unbound_required_input",
                    field=required,
                    message=(
                        f"Job '{job.job_key}' requires artifact '{required}', but no selected job "
                        "produces it and the instruction does not supply it. Restate the complete "
                        "mission or include the upstream work."
                    ),
                )
            )
        selection = next((item for item in selections if item.job_key == job.job_key), None)
        if selection is None:
            gaps.append(
                _gap(
                    layer="algorithm",
                    code="job_unselected",
                    field=job.job_key,
                    message=f"Named job '{job.job_key}' has no ability selection.",
                )
            )
            continue
        if selection.selection_status == "selected" and selection.readiness == "ready":
            continue
        if selection.readiness == "connection_required":
            gaps.append(
                _gap(
                    layer="algorithm",
                    code="connection_required",
                    field=job.job_key,
                    message=(
                        selection.selection_reason
                        or f"Job '{job.job_key}' needs a connected provider before it can run."
                    ),
                )
            )
            continue
        gaps.append(
            _gap(
                layer="algorithm",
                code=selection.readiness or "unavailable",
                field=job.job_key,
                message=(
                    selection.selection_reason or f"Job '{job.job_key}' is not ready to become named runtime work."
                ),
            )
        )
    for entry in missing_connections or ():
        provider = str(entry.get("provider") or "connection")
        action = str(entry.get("action") or "")
        if any(gap.code == "connection_required" and action in gap.message for gap in gaps):
            continue
        gaps.append(
            _gap(
                layer="algorithm",
                code="connection_required",
                field=str(entry.get("job_key") or provider),
                message=str(entry.get("message") or f"Required connection missing: {provider}."),
            )
        )

    if planner_compile_error:
        gaps.append(
            _gap(
                layer="planner",
                code="compile_failed",
                field="planned_steps",
                message=(
                    "Planning could not bind a real input for a named job. Restate the complete "
                    f"mission so each step has a concrete artifact or scope: {planner_compile_error}"
                ),
            )
        )
    if planner_provenance and planner_provenance.get("status") == "rejected":
        reason = str(planner_provenance.get("message") or planner_provenance.get("reason_code") or "rejected")
        gaps.append(
            _gap(
                layer="planner",
                code="planner_rejected",
                field="planner_proposal",
                message=(
                    "The structured planner proposal was rejected and grants no execution authority. "
                    f"Restate the complete mission or retry after correcting: {reason}"
                ),
            )
        )
    ready_job_keys = {
        item.job_key for item in selections if item.selection_status == "selected" and item.readiness == "ready"
    }
    planned_job_keys = {step.job_key for step in planned_steps}
    for job_key in sorted(ready_job_keys - planned_job_keys):
        gaps.append(
            _gap(
                layer="planner",
                code="ready_job_has_no_step",
                field=job_key,
                message=(
                    f"Ready job '{job_key}' was not compiled into a planned step. "
                    "Restate the complete mission; recovery will not invent this work."
                ),
            )
        )
    if not planned_steps:
        gaps.append(
            _gap(
                layer="planner",
                code="no_planned_steps",
                field="planned_steps",
                message=(
                    "Ajenda could not compile named steps from this instruction. Restate the "
                    "complete mission with outcomes that map to jobs and real artifacts."
                ),
            )
        )
    for step in planned_steps:
        if not step.output_contract:
            gaps.append(
                _gap(
                    layer="planner",
                    code="missing_output_artifact",
                    field=step.step_key,
                    message=(
                        f"Step '{step.step_key}' has no output artifact contract. "
                        "A status flip without an artifact is a bug; restate so the job produces a real artifact."
                    ),
                )
            )
        if step.compile_gap:
            gaps.append(
                _gap(
                    layer="planner",
                    code="unbound_tool_input",
                    field=step.step_key,
                    message=(
                        f"Step '{step.title}' could not bind a real tool input. "
                        f"Restate the complete mission: {step.compile_gap}"
                    ),
                )
            )
        step_job = BUSINESS_JOBS_BY_KEY.get(step.job_key)
        if step_job is None:
            continue
        bound_outputs = {binding.get("output_path", "").lstrip("$.") for binding in step.input_bindings}
        for required in step_job.required_inputs:
            if required not in _ARTIFACT_KEYS or required in sources or required in bound_outputs:
                continue
            producer_present = any(required in other.produced_outputs for other in jobs if other.job_key in job_keys)
            if producer_present:
                continue
            gaps.append(
                _gap(
                    layer="planner",
                    code="unbound_artifact",
                    field=required,
                    message=(
                        f"Step '{step.step_key}' requires artifact '{required}' but has no producer "
                        "binding. Restate the complete mission so jobs produce and consume real artifacts."
                    ),
                )
            )

    unique: list[LayerGap] = []
    seen: set[tuple[str, str, str]] = set()
    for gap in gaps:
        key = (gap.layer, gap.code, gap.field)
        if key in seen:
            continue
        seen.add(key)
        unique.append(gap)
    layer_order = {"interpreter": 0, "algorithm": 1, "planner": 2}
    unique.sort(key=lambda item: (layer_order.get(item.layer, 9), item.code, item.field))
    return tuple(unique[:80])


def clarifications_from_layer_gaps(
    gaps: tuple[LayerGap, ...],
    *,
    existing: list[Clarification],
) -> list[Clarification]:
    """Project algorithm/planner gaps onto restatement clarifications without dropping interpreter items."""

    merged = list(existing)
    seen = {(item.field, item.question) for item in merged}
    for gap in gaps:
        if gap.layer == "interpreter":
            continue
        if gap.code == "connection_required":
            continue
        field = f"{gap.layer}.{gap.code}"
        question = gap.message
        key = (field, question)
        if key in seen:
            continue
        merged.append(Clarification(field=field, question=question, reason=gap.code))
        seen.add(key)
    return merged


def build_intelligence_envelope(
    *,
    tenant_id: str,
    instruction: str,
    intent: MissionIntent,
    jobs: list[BusinessJob],
    planned_steps: list[PlannedStepPreview],
    selections: list[AbilitySelection] | None = None,
    missing_connections: list[dict[str, Any]] | None = None,
    planner_provenance: dict[str, Any] | None = None,
    planner_proposal: dict[str, Any] | None = None,
    planner_compile_error: str | None = None,
) -> IntelligenceEnvelope:
    """Project one composition into a replayable, non-authoritative handoff."""

    material_clause_ids = tuple(clause.clause_id for clause in intent.interpreted_clauses if clause.material)
    expected_outputs = tuple(output for job in jobs for output in job.produced_outputs if output)
    input_bindings = tuple(binding for step in planned_steps for binding in step.input_bindings)
    assumptions_raw = planner_proposal.get("assumptions") if isinstance(planner_proposal, dict) else None
    assumptions = tuple(str(item) for item in assumptions_raw) if isinstance(assumptions_raw, (list, tuple)) else ()
    layer_gaps = collect_layer_gaps(
        intent=intent,
        jobs=jobs,
        selections=list(selections or ()),
        planned_steps=planned_steps,
        missing_connections=missing_connections,
        planner_provenance=planner_provenance,
        planner_compile_error=planner_compile_error,
    )
    return IntelligenceEnvelope(
        schema_version=2,
        tenant_id=tenant_id,
        instruction_sha256=_sha256(instruction),
        normalized_instruction_sha256=_sha256(intent.normalized_instruction),
        objective=intent.objective,
        requested_outcomes=tuple(intent.requested_outcomes),
        material_clause_ids=material_clause_ids,
        context_requirements=tuple(intent.context_requirements),
        forbidden_actions=tuple(intent.effective_forbidden_actions()),
        expected_outputs=expected_outputs,
        named_job_keys=tuple(job.job_key for job in jobs),
        planned_step_keys=tuple(step.step_key for step in planned_steps),
        input_bindings=input_bindings,
        interpretation_evidence=tuple(item.model_dump(mode="json") for item in intent.interpretation_evidence),
        unresolved_fields=tuple(dict.fromkeys(gap.field for gap in layer_gaps if gap.blocking)),
        assumptions=assumptions[:30],
        layer_gaps=layer_gaps,
    )
