"""Tenant-scoped read-only finance actions."""

from __future__ import annotations

import uuid
from typing import Any

from backend.repositories.stripe_webhook_event_repository import StripeWebhookEventRepository
from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    EvidenceItem,
    FinanceInvoiceDraftInput,
    FinanceReconciliationInput,
    FinanceRevenueSyncInput,
    SideEffectClass,
    ToolInvocation,
)


def sync_revenue(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = FinanceRevenueSyncInput.model_validate(invocation.input)
    if context.session_factory is None:
        raise ValueError("vertical.finance.sync_revenue requires a session_factory")
    with context.session_factory() as session:
        receipts = StripeWebhookEventRepository(session).list_for_tenant(
            tenant_id=uuid.UUID(context.tenant_id), limit=payload.limit
        )
    records: list[dict[str, Any]] = []
    for receipt in receipts:
        data = receipt.payload_json or {}
        records.append(
            {
                "id": receipt.event_id,
                "stripe_event_id": receipt.event_id,
                "event_type": receipt.event_type,
                "amount": data.get("amount_paid"),
                "currency": data.get("currency"),
                "status": data.get("status") or "paid",
                "occurred_at": receipt.processed_at.isoformat(),
                "customer_id": data.get("customer_id"),
                "source": "stripe_webhook_events",
            }
        )
    inspected = [r.event_id for r in receipts]
    summary = f"Read {len(records)} settled Stripe revenue record(s)."
    evidence = EvidenceItem(
        evidence_type="action_result_evidence",
        evidence_source="stripe_webhook_events",
        action_name=invocation.action,
        tool_provider="stripe",
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id else None,
        summary=summary,
        structured_payload={"count": len(records), "source": "verified_webhook_receipts"},
        records_inspected=inspected,
        side_effect_class=SideEffectClass.INTERNAL_READ,
    )
    return ActionResult(
        action="vertical.finance.sync_revenue",
        provider="stripe",
        side_effect_class=SideEffectClass.INTERNAL_READ,
        output={"revenue_records": records, "count": len(records), "source": "stripe_webhook_events"},
        evidence=[evidence],
        records_inspected=inspected,
        summary=summary,
        confidence=1.0,
    )


def register_finance_actions(registry: ActionRegistry) -> None:
    registry.register(
        ActionDefinition(
            name="vertical.finance.sync_revenue",
            handler=sync_revenue,
            provider="stripe",
            input_model=FinanceRevenueSyncInput,
            side_effect_class=SideEffectClass.INTERNAL_READ,
        )
    )
    registry.register(
        ActionDefinition(
            name="vertical.finance.prepare_reconciliation",
            handler=prepare_reconciliation,
            provider="stripe",
            input_model=FinanceReconciliationInput,
            side_effect_class=SideEffectClass.INTERNAL_READ,
        )
    )
    registry.register(
        ActionDefinition(
            name="vertical.finance.prepare_invoice_drafts",
            handler=prepare_invoice_drafts,
            provider="stripe",
            input_model=FinanceInvoiceDraftInput,
            side_effect_class=SideEffectClass.INTERNAL_READ,
        )
    )


def prepare_reconciliation(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = FinanceReconciliationInput.model_validate(invocation.input)
    total = sum(float(item.get("amount") or 0) for item in payload.revenue_records)
    currencies = sorted({str(item["currency"]) for item in payload.revenue_records if item.get("currency")})
    output = {
        "reconciliation_package": {
            "record_count": len(payload.revenue_records),
            "total_amount": total,
            "currencies": currencies,
            "source": "stripe_webhook_events",
        }
    }
    summary = f"Prepared reconciliation for {len(payload.revenue_records)} settled revenue record(s)."
    evidence = EvidenceItem(
        evidence_type="action_result_evidence",
        evidence_source="stripe_webhook_events",
        action_name=invocation.action,
        tool_provider="stripe",
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id else None,
        summary=summary,
        structured_payload=output,
        side_effect_class=SideEffectClass.INTERNAL_READ,
    )
    return ActionResult(
        action="vertical.finance.prepare_reconciliation",
        provider="stripe",
        side_effect_class=SideEffectClass.INTERNAL_READ,
        output=output,
        evidence=[evidence],
        summary=summary,
        confidence=1.0,
    )


def prepare_invoice_drafts(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = FinanceInvoiceDraftInput.model_validate(invocation.input)
    drafts = [
        {
            "source_event_id": item.get("stripe_event_id"),
            "customer_id": item.get("customer_id"),
            "amount": item.get("amount"),
            "currency": item.get("currency"),
            "status": "draft",
        }
        for item in payload.revenue_records
    ]
    output = {"invoice_drafts": drafts, "count": len(drafts), "source": "stripe_webhook_events", "sendable": False}
    summary = f"Prepared {len(drafts)} invoice draft(s); no invoice was sent or persisted externally."
    evidence = EvidenceItem(
        evidence_type="action_result_evidence",
        evidence_source="stripe_webhook_events",
        action_name=invocation.action,
        tool_provider="stripe",
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id else None,
        summary=summary,
        structured_payload={"count": len(drafts), "sendable": False},
        side_effect_class=SideEffectClass.INTERNAL_READ,
    )
    return ActionResult(
        action="vertical.finance.prepare_invoice_drafts",
        provider="stripe",
        side_effect_class=SideEffectClass.INTERNAL_READ,
        output=output,
        evidence=[evidence],
        summary=summary,
        confidence=1.0,
    )
