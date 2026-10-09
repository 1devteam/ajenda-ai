"""Governed mission confirmation and persistence phase."""

from __future__ import annotations

import uuid
from typing import Any

from backend.domain.enums import MissionPlanStatus, MissionState
from backend.domain.mission import (
    MISSION_INTAKE_METADATA_KEY,
    MISSION_TASK_GRAPH_METADATA_KEY,
    Mission,
    build_mission_intake_metadata,
    build_mission_plan_contract_metadata,
    build_mission_task_graph_contract_metadata,
    normalize_mission_task_graph_contract_metadata,
)
from backend.services.mission_composition.contracts import MissionCompositionRecord, MissionIntent
from backend.services.mission_composition.deliverable_runtime_state import (
    DELIVERABLE_RUNTIME_STATE_METADATA_KEY,
    build_deliverable_runtime_state,
)
from backend.services.mission_composition.plan_compiler import compile_plan_payload, compile_task_graph_preview
from backend.services.mission_composition.proposal_store import get_proposal, put_proposal
from backend.services.mission_composition.service_contracts import MissionCompositionError
from backend.services.mission_composition.shadow_preview import build_shadow_preview
from backend.services.mission_composition.vertical_know_how import REVOPS_V1_KNOW_HOW, select_vertical_know_how
from backend.services.mission_intake_quality import (
    MissionIntakeQualityDeniedError,
    validate_mission_intake_prompt,
)
from backend.services.quota_enforcement import BudgetGateDeniedError, QuotaExceededError


class MissionCompositionConfirmationPhase:
    def confirm(
        self: Any,
        *,
        tenant_id: str,
        proposal_id: str | None = None,
        composition: MissionCompositionRecord | MissionIntent | dict[str, Any] | None = None,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Persist mission intake + plan + task graph from a composition proposal.

        Does not materialize runtime tasks, admit to queue, or invoke tools.
        """
        if self._db is None:
            raise MissionCompositionError(code="DB_REQUIRED", message="database session is required for confirm")

        # Idempotent retry: same tenant + proposal + key returns prior mission receipt.
        key = (idempotency_key or "").strip() or None
        if key and proposal_id:
            prior_record = get_proposal(tenant_id=tenant_id, proposal_id=proposal_id, db=self._db)
            if prior_record is not None and isinstance(prior_record.confirm_receipt, dict):
                receipt = prior_record.confirm_receipt
                if str(receipt.get("idempotency_key") or "") == key and receipt.get("mission_id"):
                    return {
                        "mission_id": str(receipt["mission_id"]),
                        "proposal_id": str(receipt.get("proposal_id") or proposal_id),
                        "plan_id": str(receipt.get("plan_id") or ""),
                        "allowed_actions": list(receipt.get("allowed_actions") or prior_record.allowed_actions),
                        "forbidden_actions": list(receipt.get("forbidden_actions") or prior_record.forbidden_actions),
                        "task_graph": dict(receipt.get("task_graph") or prior_record.task_graph_preview or {}),
                        "ready_to_start": bool(receipt.get("ready_to_start", True)),
                        "runtime_queued": False,
                        "grants_execution_authority": False,
                        "next_steps": list(
                            receipt.get("next_steps")
                            or [
                                "Review the mission plan",
                                "Use runtime-queue-admission when ready to execute",
                            ]
                        ),
                    }

        # Never trust client-supplied ability selections / ready flags. Resolve the
        # instruction, then re-run server-side composition (charter + credentials).
        instruction: str | None = None
        client_proposal_id = proposal_id
        if composition is not None:
            if isinstance(composition, MissionCompositionRecord):
                instruction = composition.instruction
                client_proposal_id = composition.proposal_id or proposal_id
            elif isinstance(composition, dict):
                raw_instruction = composition.get("instruction")
                if isinstance(raw_instruction, str) and raw_instruction.strip():
                    instruction = raw_instruction.strip()
                raw_pid = composition.get("proposal_id")
                if isinstance(raw_pid, str) and raw_pid.strip():
                    client_proposal_id = raw_pid.strip()
            else:
                raise MissionCompositionError(code="INVALID_COMPOSITION", message="composition must be a full record")

        if instruction is None and proposal_id:
            cached = get_proposal(tenant_id=tenant_id, proposal_id=proposal_id, db=self._db)
            if cached is None:
                raise MissionCompositionError(
                    code="PROPOSAL_NOT_FOUND",
                    message="proposal_id not found for tenant; recompose or pass composition.instruction",
                )
            instruction = cached.instruction
            client_proposal_id = cached.proposal_id

        if not instruction:
            if proposal_id:
                raise MissionCompositionError(
                    code="PROPOSAL_NOT_FOUND",
                    message="proposal_id not found for tenant; recompose or pass composition.instruction",
                )
            raise MissionCompositionError(
                code="PROPOSAL_REQUIRED",
                message="proposal_id or composition.instruction is required",
            )

        record = self.compose(tenant_id=tenant_id, instruction=instruction)
        if client_proposal_id:
            record = record.model_copy(update={"proposal_id": client_proposal_id})
            put_proposal(tenant_id=tenant_id, record=record)

        if not record.allowed_actions:
            raise MissionCompositionError(
                code="NO_RUNTIME_ACTIONS",
                message="composition has no runtime-ready allowed_actions",
            )
        if not record.ready_to_start:
            raise MissionCompositionError(
                code="PROPOSAL_NOT_READY",
                message=(
                    "composition is not ready_to_start; resolve missing connections, "
                    "charter blocks, or required jobs before confirm"
                ),
            )

        success_criteria = [
            {
                "description": item.description,
                "evidence": ["composition evidence package", "action_result_evidence"],
            }
            for item in record.intent.success_criteria
        ]
        if not success_criteria:
            success_criteria = [
                {
                    "description": "At least 1 composition deliverable with governed evidence",
                    "evidence": ["action_result_evidence"],
                }
            ]
        constraints: list[dict[str, Any]] = [
            {
                "name": item[:120],
                "description": item,
                "hard": True,
            }
            for item in record.intent.constraints
        ]
        if "gtm.email_send" in record.forbidden_actions or record.intent.send_policy.mode in {
            "forbid",
            "conditional",
        }:
            if not any("do not send" in c["description"].lower() for c in constraints):
                mode = record.intent.send_policy.mode
                constraints.append(
                    {
                        "name": "Send policy",
                        "description": (
                            "Do not send messages; drafts require human review before any future send."
                            if mode == "forbid"
                            else f"Send is conditional ({record.intent.send_policy.condition}); "
                            "not authorized for immediate delivery."
                        ),
                        "hard": True,
                    }
                )

        scope_limits = [
            f"{entity.location or 'region'} {entity.industry or entity.type} prospects only".strip()
            for entity in record.intent.target_entities
        ] or ["composition-selected outcomes for this mission only"]

        try:
            validate_mission_intake_prompt(
                objective=record.intent.objective,
                success_criteria=success_criteria,
                constraints=constraints,
                scope_limits=scope_limits,
                allowed_actions=record.allowed_actions,
                operator_notes=(
                    f"Composed from proposal {record.proposal_id}; abilities selected by mission_composition_engine."
                ),
                allow_legacy_v1=False,
            )
        except MissionIntakeQualityDeniedError as exc:
            raise MissionCompositionError(
                code="INTAKE_QUALITY",
                message=exc.to_detail().get("message", str(exc)),
            ) from exc

        quota = self._quota_enforcement_service(self._db)
        tid = uuid.UUID(str(tenant_id))
        try:
            quota.enforce_mission_budget_gate(tid, None)
            quota.check_and_record_mission_creation(tid)
        except BudgetGateDeniedError as exc:
            raise MissionCompositionError(code="BUDGET_DENIED", message=str(exc)) from exc
        except QuotaExceededError as exc:
            raise MissionCompositionError(code="QUOTA_EXCEEDED", message=str(exc)) from exc

        deliverable_runtime_state = build_deliverable_runtime_state(
            self._runtime_deliverable_request(record.intent),
            coverage_assessment=record.coverage_assessment,
            epistemic_context=record.epistemic_context,
            know_how=select_vertical_know_how(record.intent.requested_outcomes) or REVOPS_V1_KNOW_HOW,
            minimum_rows=record.intent.requested_quantity or 0,
            minimum_rows_by_artifact={
                "qualified_prospects": record.intent.qualification_quantity or record.intent.requested_quantity or 0,
                "introduction_drafts": record.intent.qualification_quantity or record.intent.requested_quantity or 0,
            },
            shadow_preview=build_shadow_preview(
                proposal_id=record.proposal_id,
                preview_id=f"{record.proposal_id}:shadow",
                task_graph=record.task_graph_preview,
                planned_artifact_keys=tuple(step.output_contract for step in record.planned_steps),
                coverage_assessment=record.coverage_assessment,
                epistemic_context=record.epistemic_context,
            ),
            graph_lineage=record.composition_provenance.graph_lineage,
        )
        intake = build_mission_intake_metadata(
            success_criteria=success_criteria,
            constraints=constraints,
            operator_notes=f"Composed from proposal {record.proposal_id} by mission_composition_engine",
            context={
                "composition": {
                    "proposal_id": record.proposal_id,
                    "schema_version": record.schema_version,
                    "instruction": record.instruction,
                    "job_assignments": [item.model_dump(mode="json") for item in record.job_assignments],
                    "ability_selections": [item.model_dump(mode="json") for item in record.ability_selections],
                    "intelligence_envelope": (
                        record.intelligence_envelope.model_dump(mode="json")
                        if record.intelligence_envelope is not None
                        else None
                    ),
                    "forbidden_actions": record.forbidden_actions,
                    "allowed_actions_provenance": record.allowed_actions_provenance.model_dump(mode="json"),
                    "missing_connections": record.missing_connections,
                    "composition_provenance": record.composition_provenance.model_dump(mode="json"),
                    "coverage_assessment": (
                        record.coverage_assessment.model_dump(mode="json")
                        if record.coverage_assessment is not None
                        else None
                    ),
                    "epistemic_context": (
                        record.epistemic_context.model_dump(mode="json")
                        if record.epistemic_context is not None
                        else None
                    ),
                    "actor_id": actor_id,
                    **(
                        {DELIVERABLE_RUNTIME_STATE_METADATA_KEY: deliverable_runtime_state}
                        if deliverable_runtime_state is not None
                        else {}
                    ),
                    "acceptance_contract": {
                        # Public research must yield at least one usable
                        # candidate even when the operator omitted a count.
                        # An empty search is a visible failure, never success.
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
                        # Public research is not complete until the observation
                        # stage promotes verified identities. Qualification may
                        # add stricter scoring, but it must not be the first
                        # point at which raw search hits become unacceptable.
                        "require_verified_identity": "research_prospects" in record.intent.requested_outcomes,
                        "require_observed_contacts": "observe_contacts" in record.intent.requested_outcomes,
                    },
                }
            },
            priority="normal",
            approval_required=bool(record.approval_gates),
            approval_expectations=list(record.approval_gates),
            budget_limits=None,
            scope_limits=scope_limits,
            allowed_actions=list(record.allowed_actions),
            allowed_tools=[],
            allow_legacy_v1=False,
        )

        mission = self._mission_repository(self._db).add(
            Mission(
                tenant_id=str(tenant_id),
                objective=record.intent.objective,
                status=MissionState.PLANNED.value,
                compliance_category="operational",
                jurisdiction="US-ALL",
                metadata_json=intake,
            )
        )

        plan_body = compile_plan_payload(
            objective=record.intent.objective,
            steps=record.planned_steps,
            success_criteria=[item.description for item in record.intent.success_criteria],
            constraints=list(record.intent.constraints),
        )
        plan_metadata = build_mission_plan_contract_metadata(**plan_body)
        plan = self._mission_plan_repository(self._db).create_or_get_active_for_mission(
            mission=mission,
            status=MissionPlanStatus.DRAFT.value,
            metadata_json=plan_metadata,
        )

        graph = compile_task_graph_preview(
            record.planned_steps,
            selections=list(record.ability_selections),
        )
        graph_metadata = build_mission_task_graph_contract_metadata(
            nodes=graph.get("nodes") if isinstance(graph.get("nodes"), list) else [],
            edges=graph.get("edges") if isinstance(graph.get("edges"), list) else [],
            metadata={
                "generated_by": "mission_composition_engine",
                "proposal_id": record.proposal_id,
                "operator_notes": "Confirmed composition graph; runtime admission not performed.",
            },
        )
        # Persist task graph on mission metadata (same storage as mission routes).
        mission_metadata = dict(mission.metadata_json or {})
        normalized_graph = normalize_mission_task_graph_contract_metadata(graph_metadata)
        mission_metadata[MISSION_TASK_GRAPH_METADATA_KEY] = normalized_graph
        # keep intake
        if MISSION_INTAKE_METADATA_KEY not in mission_metadata and MISSION_INTAKE_METADATA_KEY in intake:
            mission_metadata[MISSION_INTAKE_METADATA_KEY] = intake[MISSION_INTAKE_METADATA_KEY]
        mission.metadata_json = mission_metadata
        self._db.flush()

        result = {
            "mission_id": str(mission.id),
            "proposal_id": record.proposal_id,
            "plan_id": str(plan.id),
            "allowed_actions": list(record.allowed_actions),
            "forbidden_actions": list(record.forbidden_actions),
            "task_graph": normalized_graph,
            "ready_to_start": record.ready_to_start,
            "runtime_queued": False,
            "grants_execution_authority": False,
            "next_steps": [
                "POST /v1/missions/{mission_id}/materialize-graph",
                "POST /v1/missions/{mission_id}/runtime-admission",
                "POST /v1/missions/{mission_id}/runtime-task-materialization",
                "POST /v1/missions/{mission_id}/runtime-queue-admission",
            ],
        }
        if key:
            receipt = {
                "idempotency_key": key,
                "mission_id": result["mission_id"],
                "proposal_id": result["proposal_id"],
                "plan_id": result["plan_id"],
                "allowed_actions": result["allowed_actions"],
                "forbidden_actions": result["forbidden_actions"],
                "task_graph": result["task_graph"],
                "ready_to_start": result["ready_to_start"],
                "next_steps": result["next_steps"],
            }
            stored = record.model_copy(
                update={
                    "confirm_receipt": receipt,
                    "proposal_status": "confirmed",
                    "ready_to_start": True,
                }
            )
            persisted = put_proposal(
                tenant_id=tenant_id,
                record=stored,
                db=self._db,
                actor_id=actor_id,
                require_durable=True,
            )
            if not persisted:
                raise MissionCompositionError(
                    code="CONFIRM_RECEIPT_PERSIST_FAILED",
                    message=(
                        "mission was composed but the confirmation receipt could not be "
                        "durably stored; retry with the same idempotency_key after the store recovers"
                    ),
                )
        return result
