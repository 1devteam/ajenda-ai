"""Existing-mission plan and task-graph compilation phase."""

from __future__ import annotations

import uuid
from typing import Any

from backend.domain.enums import MissionPlanStatus
from backend.domain.mission import (
    MISSION_GRAPH_MATERIALIZATION_METADATA_KEY,
    MISSION_INTAKE_METADATA_KEY,
    MISSION_RUNTIME_ADMISSION_METADATA_KEY,
    MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY,
    MISSION_TASK_GRAPH_METADATA_KEY,
    build_graph_materialization_metadata,
    build_mission_plan_contract_metadata,
    build_mission_task_graph_contract_metadata,
    normalize_mission_task_graph_contract_metadata,
)
from backend.services.mission_composition.deliverable_runtime_state import (
    DELIVERABLE_RUNTIME_STATE_METADATA_KEY,
    build_deliverable_runtime_state,
)
from backend.services.mission_composition.plan_compiler import compile_plan_payload, compile_task_graph_preview
from backend.services.mission_composition.service_contracts import (
    COMPILER_NAME,
    COMPILER_VERSION,
    MissionCompositionError,
)
from backend.services.mission_composition.shadow_preview import build_shadow_preview
from backend.services.mission_composition.vertical_know_how import REVOPS_V1_KNOW_HOW, select_vertical_know_how
from backend.services.mission_runtime_projection import supersede_runtime_task_materialization


class MissionCompositionCompilePhase:
    def compile_for_mission(
        self: Any,
        *,
        tenant_id: str,
        mission_id: uuid.UUID,
        instruction: str | None = None,
        persist: bool = True,
        source: str = "mission_compile",
        actor_id: str | None = None,
    ) -> dict[str, Any]:
        """Compile a server-owned plan/graph for an existing mission.

        Re-runs composition from the stored composition instruction when present
        (confirmed composition missions), else client instruction, else mission objective.
        Does not queue work, create leases, or invoke tools.

        Preferring stored composition.instruction avoids recompiling from the mission
        objective restatement, which is often lossy and can fail ready_to_start even
        when the original confirmed instruction was ready.

        When persist=True, replaces mission task graph + refreshes intake allowed_actions,
        supersedes stale graph admission/materialization metadata, supersedes any active
        runtime_task_materialization, and cancels planned ExecutionTasks from the prior
        materialization so queue-admission cannot enqueue stale task IDs.
        """
        if self._db is None:
            raise MissionCompositionError(code="DB_REQUIRED", message="database session is required for compile")

        mission = self._mission_repository(self._db).get_for_tenant(mission_id=mission_id, tenant_id=tenant_id)
        if mission is None:
            raise MissionCompositionError(code="MISSION_NOT_FOUND", message="mission not found for tenant")

        metadata = dict(mission.metadata_json or {})
        intake = metadata.get(MISSION_INTAKE_METADATA_KEY)
        if not isinstance(intake, dict):
            intake = {}

        # Instruction resolution for compile:
        # 1) Explicit non-empty client instruction (intentional recompile) wins.
        # 2) Else stored composition.instruction (confirmed mission source of truth).
        # 3) Else mission.objective.
        # Dispatch UI omits instruction so it does not re-send lossy objective restatements.
        raw_context = intake.get("context")
        context: dict[str, Any] = raw_context if isinstance(raw_context, dict) else {}
        raw_composition = context.get("composition")
        composition: dict[str, Any] = raw_composition if isinstance(raw_composition, dict) else {}
        stored_instruction = composition.get("instruction")
        client_instruction = (instruction or "").strip()
        instruction_text = ""
        if client_instruction:
            instruction_text = client_instruction
        elif isinstance(stored_instruction, str) and stored_instruction.strip():
            instruction_text = stored_instruction.strip()
        else:
            instruction_text = str(mission.objective or "").strip()
        if not instruction_text:
            raise MissionCompositionError(
                code="INSTRUCTION_REQUIRED",
                message="mission has no objective/instruction to compile",
            )

        record = self.compose(tenant_id=tenant_id, instruction=instruction_text)
        graph_preview = compile_task_graph_preview(
            record.planned_steps,
            selections=list(record.ability_selections),
        )
        binding_manifest = self._binding_manifest_from_steps(record.planned_steps)
        required_credentials = self._required_credentials_from_selections(record.ability_selections)
        side_effect_summary = self._side_effect_summary_from_selections(record.ability_selections)

        display_steps = [
            {
                "sequence": step.sequence,
                "step_key": step.step_key,
                "title": step.title,
                "action": step.action_name,
                "job_key": step.job_key,
                "summary": step.description,
            }
            for step in record.planned_steps
        ]

        compile_status = "ready"
        blockers: list[dict[str, str]] = []
        if not record.allowed_actions:
            compile_status = "blocked"
            blockers.append({"code": "NO_RUNTIME_ACTIONS", "message": "no runtime-ready abilities selected"})
        elif not record.ready_to_start:
            compile_status = "blocked" if not record.clarifications else "needs_clarification"
            if record.missing_connections:
                blockers.append(
                    {
                        "code": "MISSING_CONNECTIONS",
                        "message": "required connections missing for one or more jobs",
                    }
                )
            if record.clarifications:
                clarification_msgs = [
                    str(getattr(c, "question", None) or getattr(c, "reason", None) or "").strip()
                    for c in record.clarifications
                ]
                clarification_msgs = [m for m in clarification_msgs if m]
                detail = "; ".join(clarification_msgs[:5]) if clarification_msgs else ""
                blockers.append(
                    {
                        "code": "AMBIGUITY",
                        "message": (
                            f"instruction needs clarification before ready_to_start: {detail}"
                            if detail
                            else "instruction needs clarification before ready_to_start"
                        ),
                    }
                )
            if compile_status == "blocked" and not blockers:
                blockers.append(
                    {
                        "code": "PROPOSAL_NOT_READY",
                        "message": "composition is not ready_to_start",
                    }
                )

        validation_status = "valid" if compile_status == "ready" else "invalid"
        if compile_status == "needs_clarification":
            validation_status = "warning"

        graph_metadata = build_mission_task_graph_contract_metadata(
            nodes=graph_preview.get("nodes") if isinstance(graph_preview.get("nodes"), list) else [],
            edges=graph_preview.get("edges") if isinstance(graph_preview.get("edges"), list) else [],
            metadata={
                "generated_by": "ajenda-mission-compiler",
                "compiler_name": COMPILER_NAME,
                "compiler_version": COMPILER_VERSION,
                "source": source,
                "proposal_id": record.proposal_id,
                "operator_notes": "Server-compiled graph; client graph compilers are not authority.",
            },
        )
        normalized_graph = normalize_mission_task_graph_contract_metadata(graph_metadata)

        # Fingerprint + version when persisting (same as mission task-graph route).
        graph_version = 1
        if persist and compile_status == "ready":
            from datetime import UTC, datetime

            existing_graph = metadata.get(MISSION_TASK_GRAPH_METADATA_KEY)
            if isinstance(existing_graph, dict):
                prev = existing_graph.get("graph_version")
                graph_version = int(prev) + 1 if isinstance(prev, int) and prev >= 1 else 1

            # Stamp identity fields consistent with mission routes.
            import hashlib
            import json

            content = {
                "nodes": normalized_graph.get("nodes"),
                "edges": normalized_graph.get("edges"),
                "schema_version": normalized_graph.get("schema_version"),
            }
            fingerprint = (
                "sha256:" + hashlib.sha256(json.dumps(content, sort_keys=True, default=str).encode("utf-8")).hexdigest()
            )
            normalized_graph = {
                **normalized_graph,
                "mission_id": str(mission_id),
                "graph_version": graph_version,
                "graph_fingerprint": fingerprint,
            }

            # Refresh intake allowed_actions from server composition (not kitchen-sink catalog).
            intake_updated = dict(intake)
            intake_updated["allowed_actions"] = list(record.allowed_actions)
            intake_updated["forbidden_actions"] = list(record.forbidden_actions)
            context = (
                dict(intake_updated.get("context") or {}) if isinstance(intake_updated.get("context"), dict) else {}
            )
            deliverable_runtime_state = build_deliverable_runtime_state(
                self._runtime_deliverable_request(record.intent),
                coverage_assessment=record.coverage_assessment,
                epistemic_context=record.epistemic_context,
                know_how=select_vertical_know_how(record.intent.requested_outcomes) or REVOPS_V1_KNOW_HOW,
                minimum_rows=record.intent.requested_quantity or 0,
                minimum_rows_by_artifact={
                    "qualified_prospects": record.intent.qualification_quantity
                    or record.intent.requested_quantity
                    or 0,
                    "introduction_drafts": record.intent.qualification_quantity
                    or record.intent.requested_quantity
                    or 0,
                },
                shadow_preview=build_shadow_preview(
                    proposal_id=record.proposal_id,
                    preview_id=f"{record.proposal_id}:shadow",
                    task_graph=graph_preview,
                    planned_artifact_keys=tuple(step.output_contract for step in record.planned_steps),
                    coverage_assessment=record.coverage_assessment,
                    epistemic_context=record.epistemic_context,
                ),
                graph_lineage=record.composition_provenance.graph_lineage,
            )
            context["composition"] = {
                "proposal_id": record.proposal_id,
                "schema_version": record.schema_version,
                "instruction": record.instruction,
                "compiled_by": COMPILER_NAME,
                "compiler_version": COMPILER_VERSION,
                "source": source,
                "actor_id": actor_id,
                "job_assignments": [item.model_dump(mode="json") for item in record.job_assignments],
                "ability_selections": [item.model_dump(mode="json") for item in record.ability_selections],
                "intelligence_envelope": (
                    record.intelligence_envelope.model_dump(mode="json")
                    if record.intelligence_envelope is not None
                    else None
                ),
                # These fields are part of the confirmed composition contract.
                # Recompile is a refresh of the same mission meaning; it must not
                # erase the acceptance, authority provenance, or fail-closed gaps
                # that admission and worker rollup consume downstream.
                "forbidden_actions": list(record.forbidden_actions),
                "allowed_actions_provenance": record.allowed_actions_provenance.model_dump(mode="json"),
                "missing_connections": list(record.missing_connections),
                "composition_provenance": record.composition_provenance.model_dump(mode="json"),
                "coverage_assessment": (
                    record.coverage_assessment.model_dump(mode="json")
                    if record.coverage_assessment is not None
                    else None
                ),
                "epistemic_context": (
                    record.epistemic_context.model_dump(mode="json") if record.epistemic_context is not None else None
                ),
                "acceptance_contract": {
                    "candidate_min": (
                        record.intent.requested_quantity or 1
                        if "research_prospects" in record.intent.requested_outcomes
                        else 0
                    ),
                    "qualified_min": record.intent.qualification_quantity or record.intent.requested_quantity
                    if "qualify_prospects" in record.intent.requested_outcomes
                    else 0,
                    "draft_min": record.intent.qualification_quantity or record.intent.requested_quantity
                    if "prepare_outreach" in record.intent.requested_outcomes
                    else 0,
                    "require_bound_drafts": (
                        "prepare_outreach" in record.intent.requested_outcomes
                        and bool(
                            {
                                "research_prospects",
                                "qualify_prospects",
                                "enrich_contacts",
                            }
                            & set(record.intent.requested_outcomes)
                        )
                    ),
                    "research_report_required": "synthesize_research_report" in record.intent.requested_outcomes,
                    "market_opportunities_min": 3
                    if "synthesize_research_report" in record.intent.requested_outcomes
                    else 0,
                    "business_review_required": "review_business_income" in record.intent.requested_outcomes,
                    "business_opportunities_min": 3
                    if "review_business_income" in record.intent.requested_outcomes
                    else 0,
                    "internal_crm_records_min": record.intent.requested_quantity
                    if "persist_internal_crm" in record.intent.requested_outcomes
                    else 0,
                    "internal_crm_opportunities_min": record.intent.requested_quantity
                    if "persist_internal_crm" in record.intent.requested_outcomes
                    else 0,
                    "internal_crm_readback_required": "persist_internal_crm" in record.intent.requested_outcomes,
                    "score_threshold_10": self._acceptance_score_threshold(record.intent),
                    "require_verified_identity": "research_prospects" in record.intent.requested_outcomes,
                },
                **(
                    {DELIVERABLE_RUNTIME_STATE_METADATA_KEY: deliverable_runtime_state}
                    if deliverable_runtime_state is not None
                    else {}
                ),
            }
            intake_updated["context"] = context
            metadata[MISSION_INTAKE_METADATA_KEY] = intake_updated
            metadata[MISSION_TASK_GRAPH_METADATA_KEY] = normalized_graph

            now = datetime.now(UTC).isoformat()
            # Supersede stale admission so old client graphs cannot be re-used.
            adm = metadata.get(MISSION_RUNTIME_ADMISSION_METADATA_KEY)
            if isinstance(adm, dict):
                superseded_adm = dict(adm)
                superseded_adm["admission_status"] = "superseded"
                superseded_adm["updated_at"] = now
                superseded_adm["superseded_at"] = now
                superseded_adm["superseded_reason"] = "mission_recompiled"
                metadata[MISSION_RUNTIME_ADMISSION_METADATA_KEY] = superseded_adm

            # Supersede prior runtime task materialization and cancel planned tasks so
            # runtime-queue-admission cannot enqueue stale ExecutionTasks from the old graph.
            cancelled_task_ids: list[str] = []
            task_materialization = metadata.get(MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY)
            if isinstance(task_materialization, dict):
                raw_task_ids = task_materialization.get("created_execution_task_ids")
                task_ids: list[uuid.UUID] = []
                if isinstance(raw_task_ids, list):
                    for raw_task_id in raw_task_ids:
                        try:
                            task_ids.append(uuid.UUID(str(raw_task_id)))
                        except ValueError:
                            continue
                if task_ids:
                    cancelled_tasks = self._execution_task_repository(self._db).cancel_planned_by_ids_for_mission(
                        tenant_id=tenant_id,
                        mission_id=mission_id,
                        task_ids=task_ids,
                    )
                    cancelled_task_ids = [str(task.id) for task in cancelled_tasks]
                supersede_runtime_task_materialization(
                    metadata=metadata,
                    reason="mission_recompiled",
                    updated_at=now,
                    supersession={
                        "superseded_by_graph_version": graph_version,
                        "superseded_by_graph_fingerprint": fingerprint,
                        "cancelled_execution_task_ids": cancelled_task_ids,
                    },
                )

            # Server-owned materialization (no client validation claims).
            previous_mat = metadata.get(MISSION_GRAPH_MATERIALIZATION_METADATA_KEY)
            previous_version = 0
            if isinstance(previous_mat, dict):
                prev_v = previous_mat.get("materialization_version")
                if isinstance(prev_v, int) and prev_v >= 0:
                    previous_version = prev_v
            capability_selections: list[dict[str, Any]] = []
            for node in normalized_graph.get("nodes") or []:
                if not isinstance(node, dict):
                    continue
                node_key = node.get("key") or node.get("node_key")
                if not isinstance(node_key, str) or not node_key.strip():
                    continue
                raw_cap = node.get("capability_reference")
                cap: dict[str, Any] = raw_cap if isinstance(raw_cap, dict) else {}
                capability_selections.append(
                    {
                        "node_key": node_key,
                        "capability_name": cap.get("name") or f"bridge_{node_key}",
                        "capability_version": cap.get("version") or "1.0.0",
                        "selection_reason": "Selected by ajenda-mission-compiler.",
                        "selected_by": COMPILER_NAME,
                        "alternatives_considered": [],
                    }
                )
            mat_envelope = build_graph_materialization_metadata(
                mission_id=str(mission_id),
                materialization_status="validated",
                materialization_source=COMPILER_NAME,
                materialization_source_version=COMPILER_VERSION,
                materialization_version=previous_version + 1,
                planner_provenance={
                    "planner_type": COMPILER_NAME,
                    "planner_id": COMPILER_NAME,
                    "planning_run_id": record.proposal_id,
                    "plan_schema_version": 1,
                },
                capability_selection_provenance=capability_selections,
                graph_validation_result={
                    "validation_status": "valid",
                    "summary": "Server compile validated graph structure and composition readiness.",
                    "validated_at": now,
                    "checks": [
                        {
                            "name": "compiler_ready",
                            "status": "passed",
                            "details": "compile_status=ready",
                        },
                        {
                            "name": "node_keys",
                            "status": "passed",
                            "details": f"nodes={len(capability_selections)}",
                        },
                        {
                            "name": "server_owned",
                            "status": "passed",
                            "details": "materialization authored by server compile",
                        },
                    ],
                },
                operator_review={
                    "status": "pending",
                    "notes": "Server-compiled materialization; operator review not required for draft ladder.",
                },
                graph_generation_metadata={
                    "generator": COMPILER_NAME,
                    "generation_mode": "deterministic",
                    "generated_at": now,
                    "compiler_version": COMPILER_VERSION,
                    "source_plan_version": "1",
                    "deterministic_inputs": {"source": source, "proposal_id": record.proposal_id},
                },
                deterministic_compilation_metadata={
                    "compiler_name": COMPILER_NAME,
                    "compiler_version": COMPILER_VERSION,
                    "compilation_boundary": "composition_to_task_graph",
                    "deterministic": True,
                    "input_fingerprint": fingerprint,
                    "output_fingerprint": fingerprint,
                },
                generation_notes=[
                    "Server compile wrote graph materialization; client validation claims are not accepted.",
                ],
                materialized_at=now,
                updated_at=now,
                graph_reference={
                    "metadata_key": MISSION_TASK_GRAPH_METADATA_KEY,
                    "schema_version": normalized_graph.get("schema_version"),
                    "graph_version": graph_version,
                    "graph_fingerprint": fingerprint,
                    "mission_id": str(mission_id),
                },
            )
            metadata.update(mat_envelope)

            plan_body = compile_plan_payload(
                objective=record.intent.objective,
                steps=record.planned_steps,
                success_criteria=[item.description for item in record.intent.success_criteria],
                constraints=list(record.intent.constraints),
            )
            plan_metadata = build_mission_plan_contract_metadata(**plan_body)
            self._mission_plan_repository(self._db).create_or_get_active_for_mission(
                mission=mission,
                status=MissionPlanStatus.DRAFT.value,
                metadata_json=plan_metadata,
            )

            self._mission_repository(self._db).update_metadata(mission=mission, metadata_json=metadata)
            self._db.flush()

        return {
            "compiler": {
                "name": COMPILER_NAME,
                "version": COMPILER_VERSION,
                "source": source,
            },
            "mission_id": str(mission_id),
            "proposal_id": record.proposal_id,
            "compile_status": compile_status,
            "blockers": blockers,
            "warnings": [
                {
                    "code": "CLARIFICATION",
                    "message": str(getattr(c, "question", None) or getattr(c, "reason", None) or "clarification"),
                }
                for c in record.clarifications
            ],
            "plan": compile_plan_payload(
                objective=record.intent.objective,
                steps=record.planned_steps,
                success_criteria=[item.description for item in record.intent.success_criteria],
                constraints=list(record.intent.constraints),
            ),
            "task_graph": normalized_graph,
            "binding_manifest": binding_manifest,
            "required_credentials": required_credentials,
            "required_approvals": list(record.approval_gates),
            "side_effect_summary": side_effect_summary,
            "validation": {
                "validation_status": validation_status,
                "summary": (
                    "Server composition compile completed."
                    if compile_status == "ready"
                    else "Server composition compile is not fully ready."
                ),
                "checks": [
                    {
                        "name": "allowed_actions_nonempty",
                        "status": "passed" if record.allowed_actions else "failed",
                        "details": f"count={len(record.allowed_actions)}",
                    },
                    {
                        "name": "ready_to_start",
                        "status": "passed" if record.ready_to_start else "failed",
                        "details": f"ready_to_start={record.ready_to_start}",
                    },
                    {
                        "name": "graph_nodes",
                        "status": "passed" if (normalized_graph.get("nodes") or []) else "failed",
                        "details": f"nodes={len(normalized_graph.get('nodes') or [])}",
                    },
                ],
                "validator": "server",
            },
            "display": {
                "steps": display_steps,
                "allowed_actions": list(record.allowed_actions),
                "forbidden_actions": list(record.forbidden_actions),
                "objective": record.intent.objective,
            },
            "persisted": bool(persist and compile_status == "ready"),
            "grants_execution_authority": False,
            "runtime_queued": False,
            "next_steps": [
                "POST /v1/missions/{mission_id}/materialize-graph",
                "POST /v1/missions/{mission_id}/runtime-admission",
                "POST /v1/missions/{mission_id}/runtime-task-materialization",
                "POST /v1/missions/{mission_id}/runtime-queue-admission",
            ],
        }
