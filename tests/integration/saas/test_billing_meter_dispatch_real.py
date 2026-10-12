from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import stripe
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from backend.db.tenant_session import activate_tenant_session
from backend.domain.billing_meter_dispatch import BillingMeterDispatch
from backend.domain.tenant import Tenant
from backend.domain.tenant_usage import TenantUsage
from backend.services.billing_meter_dispatcher import BillingMeterDispatchService
from backend.services.quota_enforcement import QuotaEnforcementService

pytestmark = pytest.mark.integration


def _sessions(pg_engine) -> sessionmaker:  # type: ignore[no-untyped-def, type-arg]
    return sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _tenant(session, *, stripe_customer_id: str | None = None) -> Tenant:  # type: ignore[no-untyped-def]
    tenant_id = uuid.uuid4()
    tenant = Tenant(
        id=tenant_id,
        name=f"Billing Meter {tenant_id.hex[:8]}",
        slug=f"billing-meter-{tenant_id.hex[:8]}",
        plan="pro",
        stripe_customer_id=stripe_customer_id,
    )
    session.add(tenant)
    session.flush()
    return tenant


def test_outer_rollback_removes_usage_counter_and_meter_intent(pg_engine) -> None:  # type: ignore[no-untyped-def]
    sessions = _sessions(pg_engine)
    setup = sessions()
    tenant = _tenant(setup)
    setup.commit()
    tenant_id = tenant.id
    setup.close()

    admission = sessions()
    QuotaEnforcementService(admission).check_and_record_task_creation(tenant_id, count=2)
    admission.rollback()
    admission.close()

    verify = sessions()
    assert verify.scalar(select(TenantUsage).where(TenantUsage.tenant_id == tenant_id)) is None
    assert verify.scalar(select(BillingMeterDispatch).where(BillingMeterDispatch.tenant_id == tenant_id)) is None
    verify.close()


def test_committed_usage_without_stripe_customer_is_durably_skipped(pg_engine) -> None:  # type: ignore[no-untyped-def]
    sessions = _sessions(pg_engine)
    session = sessions()
    tenant = _tenant(session)
    tenant_id = tenant.id

    QuotaEnforcementService(session).check_and_record_task_creation(tenant_id, count=2)
    session.commit()
    session.close()

    verify = sessions()
    dispatch = verify.scalar(select(BillingMeterDispatch).where(BillingMeterDispatch.tenant_id == tenant_id))
    assert dispatch is not None
    assert dispatch.quantity == 2
    assert dispatch.metric == "tasks"
    assert dispatch.status == "skipped"
    assert dispatch.attempt_count == 1
    assert dispatch.last_error == "tenant has no Stripe customer"
    verify.close()


def test_lost_stripe_ack_retries_with_same_idempotency_key_and_timestamp(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = _sessions(pg_engine)
    setup = sessions()
    tenant = _tenant(setup, stripe_customer_id="cus_meter_test")
    setup.commit()
    tenant_id = tenant.id
    setup.close()

    monkeypatch.setattr(
        "backend.services.billing_stripe_integration._build_plan_price_map",
        lambda: {"starter": "price_starter", "pro": "price_pro"},
    )
    monkeypatch.setattr(
        "stripe.Subscription.list",
        lambda **kwargs: {"data": [{"items": {"data": [{"id": "si_meter", "price": {"id": "price_pro"}}]}}]},
    )
    attempts: list[tuple[str, int, int]] = []

    def _lose_first_ack(*, subscription_item_id, quantity, timestamp, idempotency_key):  # type: ignore[no-untyped-def]
        attempts.append((idempotency_key, timestamp, quantity))
        if len(attempts) == 1:
            raise stripe.StripeError("simulated lost acknowledgement")

    monkeypatch.setattr(
        "backend.services.billing_stripe_integration._report_subscription_item_usage",
        _lose_first_ack,
    )

    admission = sessions()
    QuotaEnforcementService(admission).check_and_record_task_creation(tenant_id, count=3)
    admission.commit()
    admission.close()

    retry = sessions()
    dispatch = retry.scalar(select(BillingMeterDispatch).where(BillingMeterDispatch.tenant_id == tenant_id))
    assert dispatch is not None
    assert dispatch.status == "pending"
    assert dispatch.attempt_count == 1
    assert "lost acknowledgement" in (dispatch.last_error or "")
    dispatch.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    retry.commit()

    summary = BillingMeterDispatchService(retry).publish_due()
    assert summary.delivered_count == 1
    retry.close()

    assert len(attempts) == 2
    assert attempts[0] == attempts[1]
    assert attempts[0][0] == f"billing-meter:{dispatch.id}"
    assert attempts[0][2] == 3

    verify = sessions()
    persisted = verify.get(BillingMeterDispatch, dispatch.id)
    assert persisted is not None
    assert persisted.status == "delivered"
    assert persisted.attempt_count == 2
    assert persisted.stripe_subscription_item_id == "si_meter"
    assert persisted.reported_at is not None
    verify.close()


def test_billing_meter_dispatch_rls_hides_cross_tenant_rows(pg_engine) -> None:  # type: ignore[no-untyped-def]
    role = f"billing_meter_rls_{uuid.uuid4().hex}"
    quoted_role = f'"{role}"'
    sessions = _sessions(pg_engine)
    setup = sessions()
    tenant_a = _tenant(setup)
    tenant_b = _tenant(setup)
    setup.commit()
    tenant_a_id = tenant_a.id
    tenant_b_id = tenant_b.id
    setup.close()
    dispatch_id = uuid.uuid4()

    with pg_engine.begin() as admin:
        admin.execute(text(f"CREATE ROLE {quoted_role} NOLOGIN"))
        admin.execute(text(f"GRANT USAGE ON SCHEMA public TO {quoted_role}"))
        admin.execute(text(f"GRANT SELECT, INSERT ON billing_meter_dispatches TO {quoted_role}"))

    try:
        with pg_engine.connect() as connection:
            connection.execute(text(f"SET ROLE {quoted_role}"))
            session = Session(bind=connection, expire_on_commit=False)
            activate_tenant_session(session, str(tenant_a_id))
            session.execute(
                text(
                    """
                    INSERT INTO billing_meter_dispatches (
                        id, tenant_id, metric, quantity, status, next_attempt_at
                    ) VALUES (
                        :id, :tenant_id, 'tasks', 1, 'pending', now()
                    )
                    """
                ),
                {"id": dispatch_id, "tenant_id": tenant_a_id},
            )
            session.commit()

            activate_tenant_session(session, str(tenant_b_id))
            assert session.scalar(text("SELECT count(*) FROM billing_meter_dispatches")) == 0
            with pytest.raises(DBAPIError):
                session.execute(
                    text(
                        """
                        INSERT INTO billing_meter_dispatches (
                            id, tenant_id, metric, quantity, status, next_attempt_at
                        ) VALUES (
                            :id, :tenant_id, 'tasks', 1, 'pending', now()
                        )
                        """
                    ),
                    {"id": uuid.uuid4(), "tenant_id": tenant_a_id},
                )
                session.flush()
            session.rollback()

            connection.execute(text(f"SET ROLE {quoted_role}"))
            session.execute(text("RESET app.current_tenant_id"))
            assert session.scalar(text("SELECT count(*) FROM billing_meter_dispatches")) == 0
            session.close()
            connection.execute(text("RESET ROLE"))
            connection.commit()
    finally:
        with pg_engine.begin() as admin:
            admin.execute(text("DELETE FROM billing_meter_dispatches WHERE id = :id"), {"id": dispatch_id})
            admin.execute(
                text("DELETE FROM tenants WHERE id IN (:tenant_a_id, :tenant_b_id)"),
                {"tenant_a_id": tenant_a_id, "tenant_b_id": tenant_b_id},
            )
            admin.execute(text(f"DROP OWNED BY {quoted_role}"))
            admin.execute(text(f"DROP ROLE IF EXISTS {quoted_role}"))
