from __future__ import annotations

import uuid

from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.finance_actions import prepare_invoice_drafts, prepare_reconciliation
from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation


def _context() -> ActionRuntimeContext:
    return ActionRuntimeContext(
        tenant_id="tenant-1",
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        worker_id="worker-1",
        lease_id="lease-1",
    )


def test_finance_actions_are_registered_with_read_only_manifests() -> None:
    registry = get_default_action_registry(rebuild=True)
    assert registry.get("vertical.finance.sync_revenue").side_effect_class.value == "internal_read"
    assert registry.get("vertical.finance.prepare_reconciliation").side_effect_class.value == "internal_read"
    assert registry.get("vertical.finance.prepare_invoice_drafts").side_effect_class.value == "internal_read"


def test_reconciliation_summarizes_bound_revenue_records() -> None:
    result = prepare_reconciliation(
        ToolInvocation(
            action="vertical.finance.prepare_reconciliation",
            input={"revenue_records": [{"amount": 1250, "currency": "usd"}, {"amount": 250, "currency": "usd"}]},
        ),
        _context(),
    )
    assert result.output["reconciliation_package"] == {
        "record_count": 2,
        "total_amount": 1500.0,
        "currencies": ["usd"],
        "source": "stripe_webhook_events",
    }


def test_invoice_drafts_are_explicitly_unsendable() -> None:
    result = prepare_invoice_drafts(
        ToolInvocation(
            action="vertical.finance.prepare_invoice_drafts",
            input={
                "revenue_records": [
                    {"stripe_event_id": "evt_1", "customer_id": "cus_1", "amount": 99, "currency": "usd"}
                ]
            },
        ),
        _context(),
    )
    assert result.output["sendable"] is False
    assert result.output["invoice_drafts"][0]["status"] == "draft"
