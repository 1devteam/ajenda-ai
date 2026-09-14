"""Provider-neutral CRM observation and reconciliation proposal actions."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.record_store import record_store_limitations, resolve_record_store
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    CRMMutateInput,
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
    CRMOperationKind,
    CRMProviderObservation,
    CRMReconciliationPlan,
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


def crm_mutate(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    if not invocation.idempotency_key or not invocation.idempotency_key.strip():
        raise ValueError("crm.mutate requires an idempotency_key")
    payload = CRMMutateInput.model_validate(invocation.input)
    desired = CanonicalCRMDesiredState.model_validate(payload.desired_state)
    plan = CRMReconciliationPlan.model_validate(payload.reconciliation_plan)
    if plan.grants_execution_authority:
        raise ValueError("CRM reconciliation plan cannot grant mutation authority")
    if plan.canonical_entity_id != desired.canonical_entity_id:
        raise ValueError("CRM mutation plan does not match desired canonical entity")
    operation = plan.operation
    if operation.operation_kind == CRMOperationKind.CONFLICT:
        raise ValueError("CRM mutation cannot execute a conflict plan")

    record_id = operation.provider_record_id or _deterministic_crm_record_id(desired)
    store = resolve_record_store(context)
    existing = store.read_record(tenant_id=context.tenant_id, record_type=desired.object_type, record_id=record_id)
    existing_key = existing.get("crm_mutation_idempotency_key") if existing else None
    if existing_key and existing_key != invocation.idempotency_key:
        raise ValueError("CRM record was already mutated with a different idempotency key")
    if operation.expected_provider_version and existing is None:
        raise ValueError("CRM mutation expected an observed provider record that is no longer present")
    if operation.expected_provider_version and operation.expected_provider_version != f"record:{record_id}":
        raise ValueError("CRM mutation provider version does not match the internal record")

    desired_data = {
        **desired.fields,
        "id": record_id,
        "canonical_identity": desired.canonical_entity_id,
        "lifecycle_state": desired.lifecycle_state.value,
        "association_entity_ids": list(desired.association_entity_ids),
        "source_artifact_ids": list(desired.source_artifact_ids),
        "crm_mutation_idempotency_key": invocation.idempotency_key,
    }
    if operation.operation_kind == CRMOperationKind.NOOP:
        written = existing
        if written is None:
            raise ValueError("CRM noop mutation requires an observed record")
    else:
        written = store.write_record(
            tenant_id=context.tenant_id,
            record_type=desired.object_type,
            record_id=record_id,
            data=desired_data,
        )
    readback = store.read_record(tenant_id=context.tenant_id, record_type=desired.object_type, record_id=record_id)
    if readback != written:
        raise ValueError(f"CRM mutation read-back verification failed for {record_id}")
    now = datetime.now(UTC)
    receipt = EffectReceiptContract(
        provider="ajenda_internal",
        provider_account_id=context.tenant_id,
        action_name="crm.mutate",
        idempotency_key=invocation.idempotency_key,
        request_hash=_sha256_json(
            {"desired_state": desired.model_dump(mode="json"), "plan": plan.model_dump(mode="json")}
        ),
        attempted_at=now,
        certainty=EffectCertainty.VERIFIED,
        provider_object_ids=(record_id,),
        read_back_at=now,
        read_back_hash=_sha256_json(readback),
    )
    output = {
        "record": readback,
        "operation_kind": operation.operation_kind.value,
        "idempotency_key": invocation.idempotency_key,
        "effect_receipt": receipt.model_dump(mode="json"),
        "grants_execution_authority": False,
    }
    summary = f"Applied and read-back verified CRM {operation.operation_kind.value} for {record_id}."
    return ActionResult(
        action="crm.mutate",
        provider="ajenda_crm",
        side_effect_class=SideEffectClass.INTERNAL_WRITE,
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="crm.mutate",
                summary=summary,
                payload=output,
                inspected=[record_id],
                side_effect_class=SideEffectClass.INTERNAL_WRITE,
            )
        ],
        records_inspected=[record_id],
        records_changed=[] if operation.operation_kind == CRMOperationKind.NOOP else [record_id],
        summary=summary,
        confidence=1.0,
    )


def _deterministic_crm_record_id(desired: CanonicalCRMDesiredState) -> str:
    digest = hashlib.sha256(desired.canonical_entity_id.casefold().encode()).hexdigest()[:20]
    return f"{desired.object_type}-{digest}"


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


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
            name="crm.mutate",
            handler=crm_mutate,
            provider="ajenda_crm",
            input_model=CRMMutateInput,
            side_effect_class=SideEffectClass.INTERNAL_WRITE,
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
