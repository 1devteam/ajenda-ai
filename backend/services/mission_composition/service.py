"""MissionCompositionService — compose (read-only) and confirm (governed mutation).

Compose: no missions, plans, graphs, tasks, queue, leases, or provider side effects.
Confirm: creates mission intake + plan + task graph contracts only; never queues.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from backend.domain.enums import MissionPlanStatus, MissionState
from backend.domain.mission import (
    MISSION_GRAPH_MATERIALIZATION_METADATA_KEY,
    MISSION_INTAKE_METADATA_KEY,
    MISSION_RUNTIME_ADMISSION_METADATA_KEY,
    MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY,
    MISSION_TASK_GRAPH_METADATA_KEY,
    Mission,
    build_graph_materialization_metadata,
    build_mission_intake_metadata,
    build_mission_plan_contract_metadata,
    build_mission_task_graph_contract_metadata,
    normalize_mission_task_graph_contract_metadata,
)
from backend.repositories.business_profile_repository import BusinessProfileRepository
from backend.repositories.execution_task_repository import ExecutionTaskRepository
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
from backend.services.mission_composition.interpretation import (
    MissionInterpreter,
    MissionInterpreterOutputError,
    build_mission_interpreter,
)
from backend.services.mission_composition.interpretation.llm_client import MissionInterpreterTransportError
from backend.services.mission_composition.interpretation.review import (
    confirmed_intent_payload,
    reviewed_interpretation_payload,
)
from backend.services.mission_composition.plan_compiler import (
    compile_job_assignments,
    compile_plan_payload,
    compile_planned_steps,
    compile_task_graph_preview,
)
from backend.services.mission_composition.proposal_store import (
    ProposalStoreRecordError,
    ProposalStoreUnavailableError,
    get_proposal_for_confirmation,
    load_thread_failure_context,
    mark_superseded,
    put_proposal,
)
from backend.services.mission_intake_quality import (
    MissionIntakeQualityDeniedError,
    validate_mission_intake_prompt,
)
from backend.services.mission_runtime_projection import supersede_runtime_task_materialization
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


def _interpretation_fingerprint(intent: MissionIntent) -> str:
    """Fingerprint exactly the execution-relevant interpretation shown for review."""

    payload = reviewed_interpretation_payload(intent)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


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


def _integrations_for_credential(record: object) -> set[str]:
    """Map persisted credential rows to integration tokens used by the resolver."""

    found: set[str] = set()
    provider = str(getattr(record, "provider", "") or "").strip().lower()
    credential_id = str(getattr(record, "credential_id", "") or "").strip().lower()
    hosts_raw = getattr(record, "trusted_destination_hosts", None) or []
    hosts = {str(host).strip().lower() for host in hosts_raw if str(host).strip()}

    # SMTP is send-only — never treat it as Gmail (gtm.email_check requires Gmail API).
    is_smtp = "smtp" in credential_id or (
        provider == "external_email" and str(getattr(record, "integration", "") or "").lower() == "smtp"
    )
    if is_smtp:
        found.add("smtp")
    elif provider == "external_email" or "gmail" in credential_id or "gmail.googleapis.com" in hosts:
        found.add("gmail")
    if provider == "external_crm" or "hubspot" in credential_id or "hubapi.com" in " ".join(hosts):
        found.add("hubspot")
    # Credential-id first so Contacts never masquerades as Calendar via shared API host.
    if "google-contacts" in credential_id or "contacts" in credential_id or "people.googleapis.com" in hosts:
        found.add("google_contacts")
    if (
        "google-calendar" in credential_id
        or ("calendar" in credential_id and "contacts" not in credential_id)
        or (
            "www.googleapis.com" in hosts
            and "people.googleapis.com" not in hosts
            and "google-contacts" not in credential_id
        )
    ):
        found.add("google_calendar")
    if "salesforce" in credential_id or any("salesforce.com" in host for host in hosts):
        found.add("salesforce")
    if "linkedin" in credential_id or "api.linkedin.com" in hosts:
        found.add("linkedin")
    if "github" in credential_id or "api.github.com" in hosts:
        found.add("github")

    # Explicit integration attr if present on future schemas / projections.
    integration = getattr(record, "integration", None)
    if isinstance(integration, str) and integration.strip():
        found.add(integration.strip().lower())
    return found


def _connected_sets(
    db: Session | None, tenant_id: str
) -> tuple[set[str], set[str], dict[str, tuple[str, str]], dict[str, str]]:
    """Return credential ids, integrations, preferred (id, type) per integration, type by id."""

    if db is None:
        return set(), set(), {}, {}
    try:
        records = ProviderRuntimeCredentialRepository(db).list_for_tenant(tenant_id=tenant_id)
    except Exception:
        return set(), set(), {}, {}
    credential_ids: set[str] = set()
    integrations: set[str] = set()
    preferred_by_integration: dict[str, tuple[str, str]] = {}
    type_by_credential_id: dict[str, str] = {}
    for record in records:
        if getattr(record, "revoked", False) or getattr(record, "deleted", False):
            continue
        if getattr(record, "enabled", True) is False:
            continue
        cred_id = str(record.credential_id)
        cred_type = str(getattr(record, "credential_type", "") or "api_key").strip() or "api_key"
        credential_ids.add(cred_id)
        type_by_credential_id[cred_id] = cred_type
        for integ in _integrations_for_credential(record):
            integrations.add(integ)
            preferred_by_integration.setdefault(integ, (cred_id, cred_type))
    for catalog_id, integ in (
        ("gmail-email", "gmail"),
        ("hubspot-crm", "hubspot"),
        ("google-calendar-read", "google_calendar"),
        ("google-contacts-read", "google_contacts"),
        ("salesforce-read", "salesforce"),
        ("linkedin-read", "linkedin"),
        ("github-read", "github"),
    ):
        if catalog_id in type_by_credential_id and integ in preferred_by_integration:
            preferred_by_integration[integ] = (catalog_id, type_by_credential_id[catalog_id])
    return credential_ids, integrations, preferred_by_integration, type_by_credential_id


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

    def __init__(self, db: Session | None = None, *, interpreter: MissionInterpreter | None = None) -> None:
        self._db = db
        self._interpreter = interpreter or build_mission_interpreter()

    def _compose_from_intent(
        self,
        *,
        tenant_id: str,
        raw_instruction: str,
        intent: MissionIntent,
        interpretation_thread_id: str,
        proposal_id: str | None = None,
    ) -> MissionCompositionRecord:
        """Re-run deterministic governance and compilation for a stored interpretation."""

        charter = _load_charter(self._db, tenant_id)
        connected_ids, connected_integrations, preferred_creds, type_by_id = _connected_sets(self._db, tenant_id)

        jobs = route_jobs_for_intent(intent)
        selections, missing = resolve_jobs(
            jobs,
            intent=intent,
            charter=charter,
            connected_credential_ids=connected_ids,
            connected_integrations=connected_integrations,
            preferred_credential_by_integration=preferred_creds,
            credential_type_by_id=type_by_id,
        )
        planned_steps = compile_planned_steps(selections, intent=intent)
        job_assignments = compile_job_assignments(selections)
        task_graph_preview = compile_task_graph_preview(
            planned_steps,
            selections=selections,
            approved_by="mission_composition_engine",
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
        composition_ok = bool(allowed_actions) and required_jobs_ready
        connection_blocked = bool(missing) and not composition_ok
        ready_to_start = interpretation_ok and composition_ok and not connection_blocked

        if not interpretation_ok:
            proposal_status: str = "interpretation_failed"
        elif connection_blocked:
            proposal_status = "connection_required"
        elif not composition_ok:
            proposal_status = "composition_blocked"
        else:
            proposal_status = "proposal_ready"

        return MissionCompositionRecord(
            schema_version=COMPOSITION_SCHEMA_VERSION,
            proposal_id=proposal_id or str(uuid.uuid4()),
            interpretation_thread_id=interpretation_thread_id,
            proposal_status=proposal_status,  # type: ignore[arg-type]
            instruction=raw_instruction,
            raw_instruction=raw_instruction,
            normalized_instruction=intent.normalized_instruction or raw_instruction,
            interpretation_fingerprint=_interpretation_fingerprint(intent),
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
            composition_provenance=CompositionProvenance(
                authority_class="read_model",
                components_active=list(intent.components_executed or intent.components_active),
            ),
        )

    def compose(
        self,
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
            profile = BusinessProfileRepository(self._db).get_active_profile_for_tenant(tenant_id=tenant_id)
        try:
            intent = self._interpreter.interpret(raw_instruction, profile_context=_profile_context(profile))
        except MissionInterpreterTransportError as exc:
            raise MissionCompositionError(code=exc.code, message=str(exc)) from exc
        except MissionInterpreterOutputError as exc:
            raise MissionCompositionError(code=exc.code, message=str(exc)) from exc
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

        record = self._compose_from_intent(
            tenant_id=tenant_id,
            raw_instruction=raw_instruction,
            intent=intent,
            interpretation_thread_id=thread_id,
        )
        # Only interpretation failures escalate via thread history.
        failure_count = 0
        superseded_id = None
        if record.proposal_status == "interpretation_failed" and prior and prior.get("durable"):
            failure_count = int(prior.get("repeated_failure_count") or 0)
            superseded_id = str(prior["proposal_id"]) if prior.get("proposal_id") else None
        persisted = put_proposal(
            tenant_id=tenant_id,
            record=record,
            db=self._db,
            actor_id=actor_id,
            normalized_instruction=intent.normalized_instruction or raw_instruction,
            repeated_failure_count=failure_count,
            superseded_proposal_id=superseded_id,
            require_durable=self._db is not None,
        )
        if not persisted:
            raise MissionCompositionError(
                code="PROPOSAL_PERSIST_FAILED",
                message="the mission proposal could not be stored for confirmation; try again",
            )
        if superseded_id and record.proposal_status == "interpretation_failed":
            mark_superseded(
                tenant_id=tenant_id,
                proposal_id=superseded_id,
                superseding_proposal_id=record.proposal_id,
                db=self._db,
            )
        return record

    def confirm(
        self,
        *,
        tenant_id: str,
        proposal_id: str | None = None,
        interpretation_fingerprint: str | None = None,
        interpretation_confirmed: bool = False,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Persist mission intake + plan + task graph from a composition proposal.

        Does not materialize runtime tasks, admit to queue, or invoke tools.
        """
        if self._db is None:
            raise MissionCompositionError(code="DB_REQUIRED", message="database session is required for confirm")

        key = (idempotency_key or "").strip() or None
        if key is None:
            raise MissionCompositionError(
                code="IDEMPOTENCY_KEY_REQUIRED",
                message="idempotency_key is required when confirming a mission proposal",
            )
        if not proposal_id:
            raise MissionCompositionError(
                code="PROPOSAL_REQUIRED",
                message="proposal_id is required",
            )
        try:
            cached = get_proposal_for_confirmation(tenant_id=tenant_id, proposal_id=proposal_id, db=self._db)
        except ProposalStoreUnavailableError as exc:
            raise MissionCompositionError(
                code="PROPOSAL_STORE_UNAVAILABLE",
                message="the mission proposal store is unavailable; retry confirmation",
            ) from exc
        except ProposalStoreRecordError as exc:
            raise MissionCompositionError(
                code="INTERPRETATION_RECORD_INVALID",
                message="the stored interpretation failed integrity validation; plan the mission again",
            ) from exc
        if cached is None:
            raise MissionCompositionError(
                code="PROPOSAL_NOT_FOUND",
                message="proposal_id not found for tenant; plan the mission again",
            )
        if not interpretation_confirmed:
            raise MissionCompositionError(
                code="INTERPRETATION_CONFIRMATION_REQUIRED",
                message="confirm that the displayed interpretation matches your intent",
            )
        supplied_fingerprint = (interpretation_fingerprint or "").strip()
        if not supplied_fingerprint or supplied_fingerprint != cached.interpretation_fingerprint:
            raise MissionCompositionError(
                code="INTERPRETATION_FINGERPRINT_MISMATCH",
                message="the interpretation changed or was not the proposal you reviewed; plan the mission again",
            )
        if _interpretation_fingerprint(cached.intent) != cached.interpretation_fingerprint:
            raise MissionCompositionError(
                code="INTERPRETATION_RECORD_INVALID",
                message="the stored interpretation failed integrity validation; plan the mission again",
            )
        # A completed confirmation is proposal-idempotent even when the caller
        # lost its original retry key. The durable row lock prevents two workers
        # from passing this point before the first receipt is committed.
        if isinstance(cached.confirm_receipt, dict) and cached.confirm_receipt.get("mission_id"):
            receipt = cached.confirm_receipt
            return {
                "mission_id": str(receipt["mission_id"]),
                "proposal_id": str(receipt.get("proposal_id") or proposal_id),
                "plan_id": str(receipt.get("plan_id") or ""),
                "allowed_actions": list(receipt.get("allowed_actions") or cached.allowed_actions),
                "forbidden_actions": list(receipt.get("forbidden_actions") or cached.forbidden_actions),
                "task_graph": dict(receipt.get("task_graph") or cached.task_graph_preview or {}),
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

        # Re-run only deterministic, current governance and compilation. Re-running
        # the model here could mutate the interpretation after the human reviewed it.
        record = self._compose_from_intent(
            tenant_id=tenant_id,
            raw_instruction=cached.instruction,
            intent=cached.intent,
            interpretation_thread_id=cached.interpretation_thread_id,
            proposal_id=cached.proposal_id,
        )

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
                    "interpreted_instruction": record.normalized_instruction,
                    "interpretation_fingerprint": record.interpretation_fingerprint,
                    "interpretation_confirmed": True,
                    "intent": confirmed_intent_payload(record.intent),
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

        graph = compile_task_graph_preview(
            record.planned_steps,
            selections=list(record.ability_selections),
            approved_by=actor_id or "mission_composition_confirm",
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
        from backend.domain.mission import MISSION_TASK_GRAPH_METADATA_KEY

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
        receipt = {
            "idempotency_key": key,
            "mission_id": result["mission_id"],
            "proposal_id": result["proposal_id"],
            "plan_id": result["plan_id"],
            "allowed_actions": result["allowed_actions"],
            "forbidden_actions": result["forbidden_actions"],
            "task_graph": result["task_graph"],
            "ready_to_start": result["ready_to_start"],
            "interpretation_fingerprint": record.interpretation_fingerprint,
            "interpretation_confirmed": True,
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
                    "the mission confirmation could not be durably stored; "
                    "retry with the same idempotency_key after the store recovers"
                ),
            )
        return result

    def compile_for_mission(
        self,
        *,
        tenant_id: str,
        mission_id: uuid.UUID,
        instruction: str | None = None,
        persist: bool = True,
        source: str = "mission_compile",
        actor_id: str | None = None,
    ) -> dict[str, Any]:
        """Compile a server-owned plan/graph for an existing mission.

        Re-runs deterministic governance from the exact interpretation confirmed
        by the user. The model is never called during compile.
        Does not queue work, create leases, or invoke tools.

        Refusing new or lossy instruction text prevents interpretation drift after
        human review. A changed instruction must go through compose + confirm again.

        When persist=True, replaces mission task graph + refreshes intake allowed_actions,
        supersedes stale graph admission/materialization metadata, supersedes any active
        runtime_task_materialization, and cancels planned ExecutionTasks from the prior
        materialization so queue-admission cannot enqueue stale task IDs.
        """
        if self._db is None:
            raise MissionCompositionError(code="DB_REQUIRED", message="database session is required for compile")

        mission = MissionRepository(self._db).get_for_tenant(mission_id=mission_id, tenant_id=tenant_id)
        if mission is None:
            raise MissionCompositionError(code="MISSION_NOT_FOUND", message="mission not found for tenant")

        metadata = dict(mission.metadata_json or {})
        intake = metadata.get(MISSION_INTAKE_METADATA_KEY)
        if not isinstance(intake, dict):
            intake = {}

        raw_context = intake.get("context")
        context: dict[str, Any] = raw_context if isinstance(raw_context, dict) else {}
        raw_composition = context.get("composition")
        composition: dict[str, Any] = raw_composition if isinstance(raw_composition, dict) else {}
        stored_instruction = composition.get("interpreted_instruction") or composition.get("instruction")
        client_instruction = (instruction or "").strip()
        if client_instruction and (
            not isinstance(stored_instruction, str) or client_instruction != stored_instruction.strip()
        ):
            raise MissionCompositionError(
                code="INTERPRETATION_CONFIRMATION_REQUIRED",
                message="a changed instruction must be planned and confirmed before compile",
            )
        proposal_id = str(composition.get("proposal_id") or "").strip()
        stored_fingerprint = str(composition.get("interpretation_fingerprint") or "").strip()
        interpretation_confirmed = composition.get("interpretation_confirmed") is True
        stored_intent = composition.get("intent")
        if (
            not proposal_id
            or not stored_fingerprint
            or not interpretation_confirmed
            or not isinstance(stored_intent, dict)
        ):
            raise MissionCompositionError(
                code="CONFIRMED_INTERPRETATION_REQUIRED",
                message="mission must be created from a confirmed interpretation before it can be recompiled",
            )
        try:
            intent = MissionIntent.model_validate(stored_intent)
        except ValueError as exc:
            raise MissionCompositionError(
                code="INTERPRETATION_RECORD_INVALID",
                message="stored mission interpretation is invalid; plan the mission again",
            ) from exc
        if _interpretation_fingerprint(intent) != stored_fingerprint:
            raise MissionCompositionError(
                code="INTERPRETATION_RECORD_INVALID",
                message="stored mission interpretation failed integrity validation; plan the mission again",
            )
        instruction_text = str(stored_instruction or "")
        record = self._compose_from_intent(
            tenant_id=tenant_id,
            raw_instruction=instruction_text,
            intent=intent,
            interpretation_thread_id="confirmed-mission",
            proposal_id=proposal_id,
        )
        approved_by = (actor_id or "").strip() or "server:mission_compile"
        # Recompile graph with authenticated actor for non-forged SE auth lineage.
        graph_preview = compile_task_graph_preview(
            record.planned_steps,
            selections=list(record.ability_selections),
            approved_by=approved_by,
        )
        binding_manifest = _binding_manifest_from_steps(record.planned_steps)
        required_credentials = _required_credentials_from_selections(record.ability_selections)
        side_effect_summary = _side_effect_summary_from_selections(record.ability_selections)

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
            context["composition"] = {
                "proposal_id": record.proposal_id,
                "schema_version": record.schema_version,
                "interpreted_instruction": record.normalized_instruction,
                "interpretation_fingerprint": record.interpretation_fingerprint,
                "interpretation_confirmed": True,
                "intent": confirmed_intent_payload(record.intent),
                "compiled_by": COMPILER_NAME,
                "compiler_version": COMPILER_VERSION,
                "source": source,
                "actor_id": actor_id,
                "job_assignments": [item.model_dump(mode="json") for item in record.job_assignments],
                "ability_selections": [item.model_dump(mode="json") for item in record.ability_selections],
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
                    cancelled_tasks = ExecutionTaskRepository(self._db).cancel_planned_by_ids_for_mission(
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
            MissionPlanRepository(self._db).create_or_get_active_for_mission(
                mission=mission,
                status=MissionPlanStatus.DRAFT.value,
                metadata_json=plan_metadata,
            )

            MissionRepository(self._db).update_metadata(mission=mission, metadata_json=metadata)
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


COMPILER_NAME = "ajenda-mission-compiler"
COMPILER_VERSION = "1.0.0"


def _binding_manifest_from_steps(steps: list[Any]) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    for step in steps:
        bindings = getattr(step, "input_bindings", None) or []
        for binding in bindings:
            if not isinstance(binding, dict):
                continue
            manifest.append(
                {
                    "to_node": str(binding.get("to_step") or step.step_key),
                    "from_node": str(binding.get("from_step") or ""),
                    "output_path": str(binding.get("output_path") or ""),
                    "input_path": str(binding.get("input_path") or ""),
                    "required": True,
                    "action": step.action_name,
                }
            )
    return manifest


def _required_credentials_from_selections(selections: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in selections:
        if getattr(item, "selection_status", None) != "selected":
            continue
        if not getattr(item, "requires_connection", False) and getattr(item, "readiness", None) == "ready":
            continue
        status = "present" if getattr(item, "readiness", None) == "ready" else "missing"
        provider = None
        cred = getattr(item, "credential_reference", None)
        if isinstance(cred, dict):
            provider = cred.get("provider")
        out.append(
            {
                "action": item.action_name,
                "readiness": getattr(item, "readiness", None),
                "provider": provider,
                "status": status if getattr(item, "requires_connection", False) else "not_required",
            }
        )
    return out


def _side_effect_summary_from_selections(selections: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "action": item.action_name,
            "side_effect_class": item.side_effect_class,
            "readiness": item.readiness,
            "selection_status": item.selection_status,
        }
        for item in selections
        if item.selection_status == "selected"
    ]
