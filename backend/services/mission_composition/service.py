"""MissionCompositionService — compose (read-only) and confirm (governed mutation).

Compose: no missions, plans, graphs, tasks, queue, leases, or provider side effects.
Confirm: creates mission intake + plan + task graph contracts only; never queues.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from backend.domain.enums import MissionPlanStatus, MissionState
from backend.domain.mission import (
    MISSION_INTAKE_METADATA_KEY,
    Mission,
    build_mission_intake_metadata,
    build_mission_plan_contract_metadata,
    build_mission_task_graph_contract_metadata,
    normalize_mission_task_graph_contract_metadata,
)
from backend.repositories.business_profile_repository import BusinessProfileRepository
from backend.repositories.mission_plan_repository import MissionPlanRepository
from backend.repositories.mission_repository import MissionRepository
from backend.repositories.provider_runtime_credential_repository import (
    ProviderRuntimeCredentialRepository,
)
from backend.services.mission_composition.capability_resolver import resolve_jobs, route_jobs_for_intent
from backend.services.mission_composition.contracts import (
    COMPOSITION_SCHEMA_VERSION,
    AllowedActionsProvenance,
    CompositionProvenance,
    MissionCompositionRecord,
    MissionIntent,
)
from backend.services.mission_composition.intent_interpreter import interpret_instruction
from backend.services.mission_composition.plan_compiler import (
    compile_job_assignments,
    compile_plan_payload,
    compile_planned_steps,
    compile_task_graph_preview,
)
from backend.services.mission_composition.proposal_store import get_proposal, put_proposal
from backend.services.mission_intake_quality import (
    MissionIntakeQualityDeniedError,
    validate_mission_intake_prompt,
)
from backend.services.operating_charter import default_operating_charter, load_operating_charter
from backend.services.quota_enforcement import (
    BudgetGateDeniedError,
    QuotaEnforcementService,
    QuotaExceededError,
)


class MissionCompositionError(ValueError):
    def __init__(self, *, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _profile_context(profile: Any) -> dict[str, Any]:
    if profile is None:
        return {}
    facts = getattr(profile, "approved_facts", None) or {}
    if not isinstance(facts, dict):
        return {}
    context: dict[str, Any] = {}
    for key in ("business_name", "company", "industry", "products_services"):
        value = facts.get(key)
        if isinstance(value, str) and value.strip():
            context[key] = value.strip()
        elif isinstance(value, dict) and isinstance(value.get("value"), str):
            context[key] = value["value"].strip()
    return context


def _connected_sets(db: Session | None, tenant_id: str) -> tuple[set[str], set[str]]:
    if db is None:
        return set(), set()
    try:
        records = ProviderRuntimeCredentialRepository(db).list_for_tenant(tenant_id=tenant_id)
    except Exception:
        return set(), set()
    credential_ids: set[str] = set()
    integrations: set[str] = set()
    for record in records:
        if getattr(record, "revoked", False) or getattr(record, "deleted", False):
            continue
        credential_ids.add(str(record.credential_id))
        integration = getattr(record, "integration", None)
        if isinstance(integration, str) and integration.strip():
            integrations.add(integration.strip().lower())
    return credential_ids, integrations


def _load_charter(db: Session | None, tenant_id: str) -> Any:
    if db is None:
        return default_operating_charter()
    profile = BusinessProfileRepository(db).get_active_profile_for_tenant(tenant_id=tenant_id)
    facts = getattr(profile, "approved_facts", None) if profile is not None else None
    if not isinstance(facts, dict):
        facts = {}
    return load_operating_charter(approved_facts=facts)


class MissionCompositionService:
    """Coordinates intent → jobs → abilities → proposal without runtime authority."""

    def __init__(self, db: Session | None = None) -> None:
        self._db = db

    def compose(self, *, tenant_id: str, instruction: str) -> MissionCompositionRecord:
        if not instruction or not instruction.strip():
            raise MissionCompositionError(code="INSTRUCTION_REQUIRED", message="instruction is required")

        profile = None
        if self._db is not None:
            profile = BusinessProfileRepository(self._db).get_active_profile_for_tenant(tenant_id=tenant_id)
        intent = interpret_instruction(instruction, profile_context=_profile_context(profile))
        charter = _load_charter(self._db, tenant_id)
        connected_ids, connected_integrations = _connected_sets(self._db, tenant_id)

        jobs = route_jobs_for_intent(intent)
        selections, missing = resolve_jobs(
            jobs,
            intent=intent,
            charter=charter,
            connected_credential_ids=connected_ids,
            connected_integrations=connected_integrations,
        )
        planned_steps = compile_planned_steps(selections)
        job_assignments = compile_job_assignments(selections)
        task_graph_preview = compile_task_graph_preview(planned_steps)
        allowed_actions = [
            item.action_name for item in selections if item.selection_status == "selected" and item.readiness == "ready"
        ]
        forbidden = sorted(
            {
                *intent.forbidden_outcomes,
                *(["gtm.email_send"] if any("do not send" in c.lower() for c in intent.constraints) else []),
            }
        )
        approval_gates: list[str] = []
        if any(
            item.side_effect_class in {"external_send", "external_write", "external_publish"} for item in selections
        ):
            approval_gates.append("review_before_external_side_effect")
        if intent.approval_preference:
            approval_gates.append(intent.approval_preference)

        ready_to_start = (
            bool(allowed_actions)
            and not intent.ambiguity
            and all(item.readiness != "charter_blocked" for item in selections if item.selection_status == "selected")
        )
        # connection_required on optional alternatives does not block ready_to_start;
        # missing required connections that removed all actions does.
        if not allowed_actions:
            ready_to_start = False

        record = MissionCompositionRecord(
            schema_version=COMPOSITION_SCHEMA_VERSION,
            proposal_id=str(uuid.uuid4()),
            instruction=instruction.strip(),
            intent=intent,
            job_assignments=job_assignments,
            ability_selections=selections,
            forbidden_actions=forbidden,
            allowed_actions=allowed_actions,
            allowed_actions_provenance=AllowedActionsProvenance(),
            missing_connections=missing,
            approval_gates=sorted(set(approval_gates)),
            planned_steps=planned_steps,
            task_graph_preview=task_graph_preview,
            clarifications=list(intent.ambiguity),
            ready_to_start=ready_to_start,
            composition_provenance=CompositionProvenance(authority_class="read_model"),
        )
        put_proposal(tenant_id=tenant_id, record=record)
        return record

    def confirm(
        self,
        *,
        tenant_id: str,
        proposal_id: str | None = None,
        composition: MissionCompositionRecord | MissionIntent | dict[str, Any] | None = None,
        actor_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist mission intake + plan + task graph from a composition proposal.

        Does not materialize runtime tasks, admit to queue, or invoke tools.
        """
        if self._db is None:
            raise MissionCompositionError(code="DB_REQUIRED", message="database session is required for confirm")

        record: MissionCompositionRecord | None = None
        if composition is not None:
            if isinstance(composition, MissionCompositionRecord):
                record = composition
            elif isinstance(composition, dict):
                record = MissionCompositionRecord.model_validate(composition)
            else:
                raise MissionCompositionError(code="INVALID_COMPOSITION", message="composition must be a full record")
        elif proposal_id:
            record = get_proposal(tenant_id=tenant_id, proposal_id=proposal_id)
            if record is None:
                raise MissionCompositionError(
                    code="PROPOSAL_NOT_FOUND",
                    message="proposal_id not found for tenant; pass composition body or recompose",
                )
        else:
            raise MissionCompositionError(
                code="PROPOSAL_REQUIRED",
                message="proposal_id or composition is required",
            )

        if not record.allowed_actions:
            raise MissionCompositionError(
                code="NO_RUNTIME_ACTIONS",
                message="composition has no runtime-ready allowed_actions",
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
        if "gtm.email_send" in record.forbidden_actions:
            if not any("do not send" in c["description"].lower() for c in constraints):
                constraints.append(
                    {
                        "name": "Do not send messages",
                        "description": "Do not send messages; drafts require human review before any future send.",
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

        quota = QuotaEnforcementService(self._db)
        tid = uuid.UUID(str(tenant_id))
        try:
            quota.enforce_mission_budget_gate(tid, None)
            quota.check_and_record_mission_creation(tid)
        except BudgetGateDeniedError as exc:
            raise MissionCompositionError(code="BUDGET_DENIED", message=str(exc)) from exc
        except QuotaExceededError as exc:
            raise MissionCompositionError(code="QUOTA_EXCEEDED", message=str(exc)) from exc

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
                    "forbidden_actions": record.forbidden_actions,
                    "allowed_actions_provenance": record.allowed_actions_provenance.model_dump(mode="json"),
                    "missing_connections": record.missing_connections,
                    "composition_provenance": record.composition_provenance.model_dump(mode="json"),
                    "actor_id": actor_id,
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

        mission = MissionRepository(self._db).add(
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
        plan = MissionPlanRepository(self._db).create_or_get_active_for_mission(
            mission=mission,
            status=MissionPlanStatus.DRAFT.value,
            metadata_json=plan_metadata,
        )

        graph = compile_task_graph_preview(record.planned_steps)
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
        from backend.domain.mission import MISSION_TASK_GRAPH_METADATA_KEY

        mission_metadata = dict(mission.metadata_json or {})
        normalized_graph = normalize_mission_task_graph_contract_metadata(graph_metadata)
        mission_metadata[MISSION_TASK_GRAPH_METADATA_KEY] = normalized_graph
        # keep intake
        if MISSION_INTAKE_METADATA_KEY not in mission_metadata and MISSION_INTAKE_METADATA_KEY in intake:
            mission_metadata[MISSION_INTAKE_METADATA_KEY] = intake[MISSION_INTAKE_METADATA_KEY]
        mission.metadata_json = mission_metadata
        self._db.flush()

        return {
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
                "POST /v1/missions/{mission_id}/materialize-graph (optional provenance)",
                "POST /v1/missions/{mission_id}/runtime-task-materialization",
                "POST /v1/missions/{mission_id}/runtime-queue-admission",
            ],
        }
