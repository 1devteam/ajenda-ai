from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker

from backend.db.tenant_session import activate_tenant_session
from backend.domain.billing_meter_dispatch import BillingMeterDispatch
from backend.repositories.billing_meter_dispatch_repository import BillingMeterDispatchRepository

logger = logging.getLogger("ajenda.billing_meter_dispatcher")

_AFTER_COMMIT_BILLING_METERS = "billing_meter_dispatches_after_commit"
_SUPPORTED_METRICS = frozenset({"missions", "tasks", "agents", "api_calls"})


@dataclass(frozen=True, slots=True)
class BillingMeterIntent:
    dispatch_id: uuid.UUID
    tenant_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class BillingMeterPublishSummary:
    delivered_count: int = 0
    retry_scheduled_count: int = 0
    skipped_count: int = 0


def billing_meter_after_commit(session: Session, intent: BillingMeterIntent) -> None:
    pending: list[BillingMeterIntent] = session.info.setdefault(_AFTER_COMMIT_BILLING_METERS, [])
    if all(existing.dispatch_id != intent.dispatch_id for existing in pending):
        pending.append(intent)


@event.listens_for(Session, "after_rollback")
def _discard_uncommitted_billing_meters(session: Session) -> None:
    if session.in_nested_transaction():
        return
    session.info.pop(_AFTER_COMMIT_BILLING_METERS, None)


@event.listens_for(Session, "after_commit")
def _publish_committed_billing_meters(session: Session) -> None:
    if session.in_nested_transaction():
        return
    intents: list[BillingMeterIntent] = session.info.pop(_AFTER_COMMIT_BILLING_METERS, [])
    if not intents:
        return
    bind = session.get_bind()
    if bind is None:
        logger.error("billing_meter_after_commit_missing_bind", extra={"intent_count": len(intents)})
        return
    factory = sessionmaker(bind=bind, autoflush=False, autocommit=False, expire_on_commit=False, future=True)
    for intent in intents:
        fresh = factory()
        try:
            activate_tenant_session(fresh, str(intent.tenant_id))
            BillingMeterDispatchService(fresh).publish_one(
                tenant_id=intent.tenant_id,
                dispatch_id=intent.dispatch_id,
            )
        except Exception:
            fresh.rollback()
            logger.exception(
                "billing_meter_after_commit_publish_failed",
                extra={"dispatch_id": str(intent.dispatch_id), "tenant_id": str(intent.tenant_id)},
            )
        finally:
            fresh.close()


class BillingMeterDispatchService:
    """Persists committed usage intents and delivers them to Stripe exactly once."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._dispatches = BillingMeterDispatchRepository(session)

    def record(self, *, tenant_id: uuid.UUID, quantity: int, metric: str) -> BillingMeterDispatch:
        if quantity <= 0:
            raise ValueError("billing meter quantity must be positive")
        if metric not in _SUPPORTED_METRICS:
            raise ValueError(f"unsupported billing meter metric: {metric!r}")
        dispatch_id = uuid.uuid4()
        dispatch = self._dispatches.add(
            BillingMeterDispatch(
                id=dispatch_id,
                tenant_id=tenant_id,
                metric=metric,
                quantity=quantity,
                status="pending",
                next_attempt_at=datetime.now(UTC),
            )
        )
        billing_meter_after_commit(
            self._session,
            BillingMeterIntent(dispatch_id=dispatch_id, tenant_id=tenant_id),
        )
        return dispatch

    def publish_one(self, *, tenant_id: uuid.UUID, dispatch_id: uuid.UUID) -> BillingMeterPublishSummary:
        dispatch = self._dispatches.get_for_tenant(tenant_id=tenant_id, dispatch_id=dispatch_id)
        if dispatch is None or dispatch.status != "pending":
            self._session.rollback()
            return BillingMeterPublishSummary()
        summary = self._deliver(dispatch)
        self._session.commit()
        return summary

    def publish_due(self, *, limit: int = 25) -> BillingMeterPublishSummary:
        delivered = retried = skipped = 0
        for dispatch in self._dispatches.list_due_pending(now=datetime.now(UTC), limit=limit):
            summary = self._deliver(dispatch)
            delivered += summary.delivered_count
            retried += summary.retry_scheduled_count
            skipped += summary.skipped_count
            self._session.commit()
        return BillingMeterPublishSummary(delivered, retried, skipped)

    def _deliver(self, dispatch: BillingMeterDispatch) -> BillingMeterPublishSummary:
        from backend.services.billing_stripe_integration import StripeBillingService

        dispatch.attempt_count += 1
        timestamp = int(dispatch.created_at.timestamp())
        try:
            outcome = StripeBillingService(self._session).report_metered_usage(
                dispatch.tenant_id,
                dispatch.quantity,
                metric=dispatch.metric,
                idempotency_key=f"billing-meter:{dispatch.id}",
                timestamp=timestamp,
            )
        except Exception as exc:
            dispatch.last_error = str(exc) or exc.__class__.__name__
            dispatch.next_attempt_at = datetime.now(UTC) + self._backoff(dispatch.attempt_count)
            logger.warning(
                "billing_meter_delivery_retry_scheduled",
                extra={
                    "dispatch_id": str(dispatch.id),
                    "tenant_id": str(dispatch.tenant_id),
                    "attempt_count": dispatch.attempt_count,
                    "error": dispatch.last_error,
                },
            )
            return BillingMeterPublishSummary(retry_scheduled_count=1)

        dispatch.last_error = outcome.detail
        dispatch.stripe_subscription_item_id = outcome.subscription_item_id
        if outcome.reported:
            dispatch.status = "delivered"
            dispatch.reported_at = datetime.now(UTC)
            return BillingMeterPublishSummary(delivered_count=1)
        dispatch.status = "skipped"
        return BillingMeterPublishSummary(skipped_count=1)

    @staticmethod
    def _backoff(attempt_count: int) -> timedelta:
        return timedelta(seconds=min(3600, 2 ** min(max(attempt_count, 1), 12)))
