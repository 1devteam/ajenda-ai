from pathlib import Path

from backend.domain.enums import EventDeliveryState
from backend.domain.event_delivery import EventDelivery

MIGRATION = Path("alembic/versions/0008_add_event_delivery_foundation.py")
REPOSITORY = Path("backend/repositories/event_delivery_repository.py")

EXPECTED_STATES = {
    "pending",
    "delivering",
    "retrying",
    "delivered",
    "dead_lettered",
    "cancelled",
}


def test_event_delivery_state_vocabulary_is_complete() -> None:
    assert {state.value for state in EventDeliveryState} == EXPECTED_STATES


def test_event_delivery_idempotency_is_tenant_scoped_in_domain() -> None:
    constraints = {
        constraint.name: tuple(constraint.columns.keys())
        for constraint in EventDelivery.__table__.constraints
        if constraint.name is not None
    }

    assert constraints["uq_event_deliveries_tenant_id_idempotency_key"] == (
        "tenant_id",
        "idempotency_key",
    )
    assert EventDelivery.__table__.columns["idempotency_key"].unique is not True


def test_event_delivery_idempotency_is_tenant_scoped_in_migration() -> None:
    migration = MIGRATION.read_text()

    assert "uq_event_deliveries_tenant_id_idempotency_key" in migration
    assert '["tenant_id", "idempotency_key"]' in migration
    assert "uq_event_deliveries_idempotency_key" not in migration


def test_event_delivery_repository_initializes_python_defaults_before_flush() -> None:
    repository = REPOSITORY.read_text()

    assert "attempts=0" in repository
    assert "status=EventDeliveryState.PENDING.value" in repository


def test_event_delivery_repository_keeps_tenant_read_boundary() -> None:
    repository = REPOSITORY.read_text()

    assert "delivery is None or delivery.tenant_id != tenant_id" in repository
    assert "event delivery not found for tenant" in repository


def test_event_delivery_foundation_has_no_transport_side_effects() -> None:
    repository = REPOSITORY.read_text()

    forbidden_transport_terms = ("requests.", "httpx.", "aiohttp", "urllib")
    for term in forbidden_transport_terms:
        assert term not in repository
