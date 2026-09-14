"""Provider-neutral CRM observation and reconciliation proposal actions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.record_store import record_store_limitations, resolve_record_store
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    CRMObserveInput,
    CRMReconcileInput,
    EvidenceItem,
    SideEffectClass,
    ToolInvocation,
)
from backend.services.vertical_ops.crm_reconciliation import (
    CanonicalCRMDesiredState,
    CRMLifecycleState,
    CRMProviderObservation,
    plan_crm_reconciliation,
)
from backend.services.vertical_ops.graft1st_contracts import IdentityMatchDecision


def _evidence(
    *,
    context: ActionRuntimeContext,
    action: str,
    summary: str,
    payload: dict[str, Any],
    inspected: list[str],
    side_effect_class: SideEffectClass,
) -> EvidenceItem:
    return EvidenceItem(
        evidence_type="action_result",
        evidence_source=f"tool.invoke.{action}",
        action_name=action,
        tool_provider="ajenda_crm",
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id is not None else None,
        summary=summary,
        structured_payload=payload,
        records_inspected=inspected,
        limitations=record_store_limitations(context),
        provenance={"runtime_path": "TaskDispatcher -> tool.invoke -> ActionRegistry -> CRM"},
        side_effect_class=side_effect_class,
    )


def _lifecycle_state(record: dict[str, Any]) -> str | None:
    value = record.get("lifecycle_state") or record.get("stage")
    return str(value) if value is not None else None


def _observation(*, context: ActionRuntimeContext, record_type: str, record: dict[str, Any]) -> CRMProviderObservation:
    record_id = str(record.get("id") or "").strip()
    if not record_id:
        raise ValueError("CRM record observation requires a stable record id")
    lifecycle = _lifecycle_state(record)
    valid_states = {item.value for item in CRMLifecycleState}
    fields: dict[str, str | int | float | bool | None] = {
        str(key): value
        for key, value in record.items()
        if key not in {"id", "canonical_identity", "stage", "lifecycle_state"}
        and isinstance(value, (str, int, float, bool))
    }
    associations = tuple(str(record[key]) for key in ("account_id", "contact_id") if record.get(key) is not None)
    return CRMProviderObservation(
        provider="ajenda_internal",
        provider_account_id=context.tenant_id,
        provider_record_id=record_id,
        canonical_entity_id=str(record.get("canonical_identity") or f"{record_type}:{record_id}"),
        object_type=record_type,
        lifecycle_state=CRMLifecycleState(lifecycle) if lifecycle in valid_states else None,
        fields=fields,
        association_entity_ids=associations,
        provider_version=f"record:{record_id}",
        observed_at_iso=datetime.now(UTC).isoformat(),
    )


def crm_observe(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = CRMObserveInput.model_validate(invocation.input)
    store = resolve_record_store(context)
    if payload.record_id:
        records = [
            record
            for record in [
                store.read_record(
                    tenant_id=context.tenant_id,
                    record_type=payload.record_type,
                    record_id=payload.record_id,
                )
            ]
            if record is not None
        ]
    else:
        records = store.search_records(
            tenant_id=context.tenant_id,
            record_type=payload.record_type,
            query=payload.query,
            limit=payload.limit,
        )
    observations = [
        _observation(context=context, record_type=payload.record_type, record=record).model_dump(mode="json")
        for record in records
    ]
    output = {"record_type": payload.record_type, "observations": observations, "count": len(observations)}
    inspected = [str(item["provider_record_id"]) for item in observations]
    summary = f"Observed {len(observations)} internal CRM {payload.record_type} record(s)."
    return ActionResult(
        action="crm.observe",
        provider="ajenda_crm",
        side_effect_class=SideEffectClass.INTERNAL_READ,
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="crm.observe",
                summary=summary,
                payload=output,
                inspected=inspected,
                side_effect_class=SideEffectClass.INTERNAL_READ,
            )
        ],
        records_inspected=inspected,
        summary=summary,
        confidence=1.0,
    )


def crm_reconcile(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = CRMReconcileInput.model_validate(invocation.input)
    desired = CanonicalCRMDesiredState.model_validate(payload.desired_state)
    identity = IdentityMatchDecision.model_validate(payload.identity_decision)
    observation = CRMProviderObservation.model_validate(payload.observation) if payload.observation else None
    plan = plan_crm_reconciliation(desired=desired, identity_decision=identity, observation=observation)
    output = {"reconciliation_plan": plan.model_dump(mode="json"), "grants_execution_authority": False}
    summary = f"Prepared CRM reconciliation plan {plan.plan_id}; no mutation was executed."
    return ActionResult(
        action="crm.reconcile",
        provider="ajenda_crm",
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="crm.reconcile",
                summary=summary,
                payload=output,
                inspected=[],
                side_effect_class=SideEffectClass.NONE,
            )
        ],
        summary=summary,
        confidence=1.0,
    )


def register_crm_actions(registry: ActionRegistry) -> None:
    registry.register(
        ActionDefinition(
            name="crm.observe",
            handler=crm_observe,
            provider="ajenda_crm",
            input_model=CRMObserveInput,
            side_effect_class=SideEffectClass.INTERNAL_READ,
        )
    )
    registry.register(
        ActionDefinition(
            name="crm.reconcile",
            handler=crm_reconcile,
            provider="ajenda_crm",
            input_model=CRMReconcileInput,
        )
    )
