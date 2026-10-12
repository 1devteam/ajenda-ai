from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from backend.services.billing_meter_dispatcher import (
    _AFTER_COMMIT_BILLING_METERS,
    BillingMeterDispatchService,
    BillingMeterIntent,
    billing_meter_after_commit,
)
from backend.services.billing_stripe_integration import MeteredUsageReportResult


def _dispatch() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        metric="tasks",
        quantity=3,
        status="pending",
        attempt_count=0,
        next_attempt_at=datetime.now(UTC),
        last_error=None,
        stripe_subscription_item_id=None,
        reported_at=None,
        created_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
    )


def test_nested_commit_does_not_consume_outer_billing_intent() -> None:
    session = Session(create_engine("sqlite://"))
    session.execute(text("SELECT 1"))
    intent = BillingMeterIntent(dispatch_id=uuid.uuid4(), tenant_id=uuid.uuid4())
    billing_meter_after_commit(session, intent)

    with session.begin_nested():
        session.execute(text("SELECT 1"))

    assert session.info[_AFTER_COMMIT_BILLING_METERS] == [intent]
    session.rollback()
    assert _AFTER_COMMIT_BILLING_METERS not in session.info


@pytest.mark.parametrize("quantity", [0, -1])
def test_record_rejects_nonpositive_quantity(quantity: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        BillingMeterDispatchService(MagicMock()).record(
            tenant_id=uuid.uuid4(),
            quantity=quantity,
            metric="tasks",
        )


def test_record_rejects_unknown_metric() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        BillingMeterDispatchService(MagicMock()).record(
            tenant_id=uuid.uuid4(),
            quantity=1,
            metric="unknown",
        )


def test_publish_due_marks_delivery_and_uses_stable_request_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    session = MagicMock()
    service = BillingMeterDispatchService(session)
    dispatch = _dispatch()
    service._dispatches = MagicMock()
    service._dispatches.list_due_pending.return_value = [dispatch]
    calls: list[dict[str, object]] = []

    class _FakeBilling:
        def __init__(self, billing_session) -> None:
            assert billing_session is session

        def report_metered_usage(self, tenant_id, quantity, **kwargs):  # type: ignore[no-untyped-def]
            calls.append({"tenant_id": tenant_id, "quantity": quantity, **kwargs})
            return MeteredUsageReportResult(True, "usage reported", "si_123")

    monkeypatch.setattr("backend.services.billing_stripe_integration.StripeBillingService", _FakeBilling)

    summary = service.publish_due()

    assert summary.delivered_count == 1
    assert dispatch.status == "delivered"
    assert dispatch.attempt_count == 1
    assert dispatch.stripe_subscription_item_id == "si_123"
    assert dispatch.reported_at is not None
    assert calls == [
        {
            "tenant_id": dispatch.tenant_id,
            "quantity": 3,
            "metric": "tasks",
            "idempotency_key": f"billing-meter:{dispatch.id}",
            "timestamp": int(dispatch.created_at.timestamp()),
        }
    ]
    session.commit.assert_called_once_with()


def test_retry_keeps_identity_then_converges_without_duplicate_quantity(monkeypatch: pytest.MonkeyPatch) -> None:
    session = MagicMock()
    service = BillingMeterDispatchService(session)
    dispatch = _dispatch()
    service._dispatches = MagicMock()
    service._dispatches.list_due_pending.return_value = [dispatch]
    identities: list[tuple[str, int]] = []
    outcomes: list[object] = [RuntimeError("stripe unavailable"), MeteredUsageReportResult(True, "ok", "si_1")]

    class _FakeBilling:
        def __init__(self, billing_session) -> None:
            pass

        def report_metered_usage(self, tenant_id, quantity, **kwargs):  # type: ignore[no-untyped-def]
            identities.append((kwargs["idempotency_key"], kwargs["timestamp"]))
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    monkeypatch.setattr("backend.services.billing_stripe_integration.StripeBillingService", _FakeBilling)

    first = service.publish_due()
    second = service.publish_due()

    assert first.retry_scheduled_count == 1
    assert second.delivered_count == 1
    assert dispatch.attempt_count == 2
    assert dispatch.status == "delivered"
    assert identities[0] == identities[1]


def test_terminal_skip_is_observable(monkeypatch: pytest.MonkeyPatch) -> None:
    session = MagicMock()
    service = BillingMeterDispatchService(session)
    dispatch = _dispatch()
    service._dispatches = MagicMock()
    service._dispatches.list_due_pending.return_value = [dispatch]

    class _FakeBilling:
        def __init__(self, billing_session) -> None:
            pass

        def report_metered_usage(self, tenant_id, quantity, **kwargs):  # type: ignore[no-untyped-def]
            return MeteredUsageReportResult(False, "tenant has no Stripe customer")

    monkeypatch.setattr("backend.services.billing_stripe_integration.StripeBillingService", _FakeBilling)

    summary = service.publish_due()

    assert summary.skipped_count == 1
    assert dispatch.status == "skipped"
    assert dispatch.last_error == "tenant has no Stripe customer"
