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
    CRMVerifyEffectInput,
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
from backend.services.vertical_ops.graft1st_contracts import (
    EffectCertainty,
    EffectReceiptContract,
    IdentityMatchDecision,
)


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


def crm_verify_effect(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = CRMVerifyEffectInput.model_validate(invocation.input)
    desired = CanonicalCRMDesiredState.model_validate(payload.desired_state)
    receipt = EffectReceiptContract.model_validate(payload.effect_receipt)
    observation = (
        CRMProviderObservation.model_validate(payload.readback_observation) if payload.readback_observation else None
    )

    reasons: list[str] = []
    equivalent = False
    if receipt.provider_account_id != context.tenant_id:
        raise ValueError("CRM effect receipt provider account does not match runtime tenant")
    if receipt.certainty == EffectCertainty.VERIFIED:
        if observation is None:
            reasons.append("verified receipt is missing read-back observation")
        elif observation.provider_record_id not in receipt.provider_object_ids:
            reasons.append("read-back record is not named by the effect receipt")
        elif observation.canonical_entity_id != desired.canonical_entity_id:
            reasons.append("read-back canonical identity differs from desired state")
        elif observation.object_type != desired.object_type:
            reasons.append("read-back object type differs from desired state")
        else:
            field_matches = all(observation.fields.get(key) == value for key, value in desired.fields.items())
            associations_match = set(desired.association_entity_ids) <= set(observation.association_entity_ids)
            lifecycle_matches = observation.lifecycle_state == desired.lifecycle_state
            equivalent = field_matches and associations_match and lifecycle_matches
            if not equivalent:
                reasons.append("read-back state does not equal desired canonical state")
    elif receipt.certainty == EffectCertainty.REJECTED:
        reasons.append("provider rejected the attempted effect")
    else:
        reasons.append("provider effect remains ambiguous and cannot be promoted to verified")

    output = {
        "effect_receipt": receipt.model_dump(mode="json"),
        "readback_observation": observation.model_dump(mode="json") if observation else None,
        "equivalent": equivalent,
        "verified": receipt.certainty == EffectCertainty.VERIFIED and equivalent,
        "reasons": reasons,
        "grants_execution_authority": False,
    }
    summary = (
        "Verified CRM effect read-back matches desired state."
        if output["verified"]
        else "CRM effect read-back was not verified; no execution authority was granted."
    )
    inspected = list(receipt.provider_object_ids)
    return ActionResult(
        action="crm.verify_effect",
        provider="ajenda_crm",
        side_effect_class=SideEffectClass.INTERNAL_READ,
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="crm.verify_effect",
                summary=summary,
                payload=output,
                inspected=inspected,
                side_effect_class=SideEffectClass.INTERNAL_READ,
            )
        ],
        records_inspected=inspected,
        summary=summary,
        confidence=1.0 if output["verified"] else 0.0,
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
            name="crm.verify_effect",
            handler=crm_verify_effect,
            provider="ajenda_crm",
            input_model=CRMVerifyEffectInput,
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
