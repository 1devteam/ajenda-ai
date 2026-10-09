"""Read-only mission composition proposal phase."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from backend.repositories.tenant_internal_record_repository import TenantInternalRecordRepository
from backend.services.mission_composition.capability_resolver import resolve_jobs, route_jobs_for_intent
from backend.services.mission_composition.contracts import (
    COMPOSITION_SCHEMA_VERSION,
    AllowedActionsProvenance,
    CompositionProvenance,
    MissionCompositionRecord,
)
from backend.services.mission_composition.coverage import assess_coverage, coverage_mode_for_intent
from backend.services.mission_composition.epistemic import build_epistemic_context
from backend.services.mission_composition.intelligence_envelope import (
    build_intelligence_envelope,
    clarifications_from_layer_gaps,
)
from backend.services.mission_composition.intent_interpreter import interpret_instruction
from backend.services.mission_composition.job_catalog import BUSINESS_JOBS_BY_KEY
from backend.services.mission_composition.plan_compiler import (
    compile_job_assignments,
    compile_task_graph_preview,
)
from backend.services.mission_composition.proposal_store import (
    load_thread_failure_context,
    mark_superseded,
    put_proposal,
)
from backend.services.mission_composition.semantic_lattice.resolver import build_semantic_selection
from backend.services.mission_composition.service_contracts import MissionCompositionError
from backend.services.mission_composition.structured_planner import PlannerRequest, validate_planner_proposal
from backend.services.mission_composition.vertical_know_how import (
    select_vertical_know_how,
    validate_know_how_runtime_references,
)


class MissionCompositionProposalPhase:
    def compose(
        self: Any,
        *,
        tenant_id: str,
        instruction: str,
        actor_id: str | None = None,
        interpretation_thread_id: str | None = None,
    ) -> MissionCompositionRecord:
        if not instruction or not instruction.strip():
            raise MissionCompositionError(code="INSTRUCTION_REQUIRED", message="instruction is required")

        # Preserve exact raw instruction; validation uses strip only for emptiness.
        raw_instruction = instruction
        thread_id = (interpretation_thread_id or "").strip() or str(uuid.uuid4())
        prior = load_thread_failure_context(
            tenant_id=tenant_id,
            actor_id=actor_id,
            interpretation_thread_id=thread_id,
            db=self._db,
        )

        profile = None
        if self._db is not None:
            profile = self._business_profile_repository(self._db).get_active_profile_for_tenant(tenant_id=tenant_id)
        intent = interpret_instruction(raw_instruction, profile_context=self._profile_context(profile))
        # Escalation only for same actor+thread interpretation failures (durable required).
        if prior and prior.get("durable") and intent.ambiguity and not intent.interpretation_ready:
            shared = set(prior.get("unresolved_fields") or []) & {c.field for c in intent.ambiguity}
            if shared:
                example = (
                    "Find five roofing companies in Northwest Arkansas, qualify them, "
                    "and prepare draft emails for review without sending them."
                )
                escalated = []
                for item in intent.ambiguity:
                    if item.field in shared:
                        escalated.append(
                            item.model_copy(
                                update={
                                    "question": (
                                        f"{item.question} The revised mission still does not include "
                                        f"required detail for '{item.field}'. Restate the full mission "
                                        f"in this form: '{example}'"
                                    )[:1000]
                                }
                            )
                        )
                    else:
                        escalated.append(item)
                intent = intent.model_copy(update={"ambiguity": escalated})

        charter = self._load_charter(self._db, tenant_id)
        connected_ids, connected_integrations, preferred_creds, type_by_id = self._connected_sets(self._db, tenant_id)
        internal_capacity: int | None = None
        if self._db is not None and coverage_mode_for_intent(intent) == "internal_crm":
            internal_capacity = TenantInternalRecordRepository(self._db).count_records(
                tenant_id=tenant_id,
                record_type="account",
            )
        coverage_assessment = assess_coverage(intent, internal_capacity=internal_capacity)
        epistemic_context = build_epistemic_context(intent, coverage_assessment)
        tenant_semantic_overrides, tenant_override_conflicts = self._tenant_semantic_overrides(profile)

        jobs = route_jobs_for_intent(intent)
        know_how = select_vertical_know_how(intent.requested_outcomes)
        if know_how is not None:
            validate_know_how_runtime_references(know_how)
        planner_proposal: dict[str, Any] | None = None
        planner_provenance: dict[str, Any] | None = None
        if know_how is not None and self._planner_provider is not None:
            material_clauses = tuple(
                {
                    "clause_id": clause.clause_id,
                    "text": clause.text,
                    "mapped_outcomes": list(clause.mapped_outcomes),
                    "status": clause.status,
                }
                for clause in intent.interpreted_clauses
                if clause.material
            )
            request = PlannerRequest(
                instruction=raw_instruction,
                raw_instruction_sha256=hashlib.sha256(raw_instruction.encode("utf-8")).hexdigest(),
                know_how_id=know_how.know_how_id,
                know_how_version=know_how.know_how_version,
                allowed_job_keys=tuple(job_key for stage in know_how.stages for job_key in stage.job_keys),
                material_clauses=material_clauses,
            )
            try:
                planner_result = self._planner_provider.propose(request)
                validate_planner_proposal(
                    planner_result.proposal,
                    know_how=know_how,
                    expected_material_clause_ids={str(item["clause_id"]) for item in material_clauses},
                    required_job_keys={job.job_key for job in jobs},
                    connected_integrations=connected_integrations,
                )
            except Exception as exc:
                planner_provenance = {
                    "status": "rejected",
                    "reason_code": f"PLANNER_{type(exc).__name__.upper()}",
                    "message": str(exc)[:500],
                    "grants_execution_authority": False,
                }
            else:
                planner_proposal = planner_result.proposal.model_dump(mode="json")
                planner_provenance = {
                    "status": "validated_proposal",
                    "provider": planner_result.provider,
                    "model": planner_result.model,
                    "provider_request_id": planner_result.provider_request_id,
                    "instruction_sha256": request.raw_instruction_sha256,
                    "grants_execution_authority": False,
                }
                jobs = [BUSINESS_JOBS_BY_KEY[item.job_key] for item in planner_result.proposal.jobs]
        selections, missing = resolve_jobs(
            jobs,
            intent=intent,
            charter=charter,
            connected_credential_ids=connected_ids,
            connected_integrations=connected_integrations,
            preferred_credential_by_integration=preferred_creds,
            credential_type_by_id=type_by_id,
        )
        if epistemic_context.budget_status == "exceeded":
            missing.append(
                {
                    "kind": "epistemic_budget_exceeded",
                    "message": "; ".join(epistemic_context.budget_excesses),
                }
            )
        semantic_selection = build_semantic_selection(
            instruction=raw_instruction,
            requested_outcomes=intent.requested_outcomes,
            selected_job_keys=(job.job_key for job in jobs),
            tenant_overrides=tenant_semantic_overrides,
            tenant_override_conflicts=tenant_override_conflicts,
        )
        for conflict in semantic_selection.conflicts:
            missing.append({"kind": "semantic_conflict", "message": conflict})
        planner_compile_error: str | None = None
        try:
            planned_steps = self._compile_planned_steps(selections, intent=intent)
        except ValueError as exc:
            # Keep named jobs even when a selected action cannot bind inputs.
            # This is a planner gap on the shared envelope, not an API abort
            # and not an interpretation failure.
            planner_compile_error = str(exc)
            try:
                planned_steps = self._compile_planned_steps(selections, intent=None)
            except ValueError:
                planned_steps = []
        job_assignments = compile_job_assignments(selections)
        task_graph_preview = compile_task_graph_preview(
            planned_steps,
            selections=selections,
        )
        intelligence_envelope = build_intelligence_envelope(
            tenant_id=tenant_id,
            instruction=raw_instruction,
            intent=intent,
            jobs=jobs,
            planned_steps=planned_steps,
            selections=selections,
            missing_connections=missing,
            planner_provenance=planner_provenance,
            planner_proposal=planner_proposal,
            planner_compile_error=planner_compile_error,
        )
        allowed_actions = [
            item.action_name for item in selections if item.selection_status == "selected" and item.readiness == "ready"
        ]
        forbidden = list(intent.effective_forbidden_actions())
        approval_gates: list[str] = []
        if any(
            item.side_effect_class in {"external_send", "external_write", "external_publish"} for item in selections
        ):
            approval_gates.append("review_before_external_side_effect")
        if intent.approval_preference:
            approval_gates.append(intent.approval_preference)

        ready_job_keys = {
            item.job_key for item in selections if item.selection_status == "selected" and item.readiness == "ready"
        }
        required_jobs_ready = all(job.job_key in ready_job_keys for job in jobs if job.maturity == "runtime_bound")
        interpretation_ok = bool(intent.interpretation_ready) and not intent.ambiguity
        composition_ok = bool(allowed_actions) and required_jobs_ready and not semantic_selection.conflicts
        connection_blocked = bool(missing) and not composition_ok
        blocking_gaps = [gap for gap in intelligence_envelope.layer_gaps if gap.blocking]
        ready_to_start = (
            interpretation_ok
            and composition_ok
            and not connection_blocked
            and not blocking_gaps
            and coverage_assessment.ready
        )
        named_work = bool(jobs)

        if not named_work:
            proposal_status: str = "interpretation_failed"
        elif connection_blocked:
            proposal_status = "connection_required"
        elif blocking_gaps or not composition_ok or not coverage_assessment.ready:
            proposal_status = "gaps_open"
        else:
            proposal_status = "proposal_ready"

        record = MissionCompositionRecord(
            schema_version=COMPOSITION_SCHEMA_VERSION,
            proposal_id=str(uuid.uuid4()),
            interpretation_thread_id=thread_id,
            proposal_status=proposal_status,  # type: ignore[arg-type]
            instruction=raw_instruction,
            raw_instruction=raw_instruction,
            normalized_instruction=intent.normalized_instruction or raw_instruction,
            intent=intent,
            job_assignments=job_assignments,
            ability_selections=selections,
            forbidden_actions=forbidden,
            allowed_actions=allowed_actions,
            allowed_actions_provenance=AllowedActionsProvenance(),
            missing_connections=missing,
            approval_gates=sorted(set(approval_gates)),
            planned_steps=planned_steps,
            intelligence_envelope=intelligence_envelope,
            coverage_assessment=coverage_assessment,
            epistemic_context=epistemic_context,
            task_graph_preview=task_graph_preview,
            planner_proposal=planner_proposal,
            planner_provenance=planner_provenance,
            clarifications=clarifications_from_layer_gaps(
                intelligence_envelope.layer_gaps,
                existing=list(intent.ambiguity),
            ),
            ready_to_start=ready_to_start,
            composition_provenance=CompositionProvenance(
                authority_class="read_model",
                know_how_id=know_how.know_how_id if know_how is not None else None,
                know_how_version=know_how.know_how_version if know_how is not None else None,
                components_active=list(intent.components_executed or intent.components_active),
                semantic_selection=semantic_selection,
            ),
        )
        # Only interpretation failures escalate via thread history.
        failure_count = 0
        superseded_id = None
        if proposal_status == "interpretation_failed" and prior and prior.get("durable"):
            failure_count = int(prior.get("repeated_failure_count") or 0)
            superseded_id = str(prior["proposal_id"]) if prior.get("proposal_id") else None
        put_proposal(
            tenant_id=tenant_id,
            record=record,
            db=self._db,
            actor_id=actor_id,
            normalized_instruction=intent.normalized_instruction or raw_instruction,
            repeated_failure_count=failure_count,
            superseded_proposal_id=superseded_id,
            require_durable=False,
        )
        if superseded_id and proposal_status == "interpretation_failed":
            mark_superseded(
                tenant_id=tenant_id,
                proposal_id=superseded_id,
                superseding_proposal_id=record.proposal_id,
                db=self._db,
            )
        return record
