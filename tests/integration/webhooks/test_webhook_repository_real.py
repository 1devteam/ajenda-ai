"""Integration tests: WebhookRepository and WebhookDispatchService against real Postgres.

These tests catch issues that the mock-backed unit tests cannot surface:

  - PostgreSQL ARRAY @> containment operator for event_type filtering
  - UUID column handling with psycopg v3
  - JSONB payload storage and retrieval
  - Atomic disable_endpoint UPDATE behaviour
  - count_recent_failures query correctness
  - Cross-tenant isolation: endpoint from tenant-A must not be visible to tenant-B
  - Delivery record persistence and retrieval ordering

All tests use the pg_session fixture from tests/integration/conftest.py.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from backend.domain.webhook_delivery import WebhookDelivery
from backend.domain.webhook_endpoint import WebhookEndpoint
from backend.repositories.webhook_repository import WebhookRepository

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()


def _make_endpoint(
    tenant_id: uuid.UUID = TENANT_A,
    url: str = "https://example.com/hook",
    event_types: list[str] | None = None,
    is_active: bool = True,
) -> WebhookEndpoint:
    return WebhookEndpoint(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        url=url,
        secret_hash="$2b$12$fakehashforintegrationtest",
        event_types=event_types or ["task.completed"],
        is_active=is_active,
    )


def _make_delivery(
    endpoint: WebhookEndpoint,
    status: str = "delivered",
    attempt_number: int = 1,
    http_status_code: int | None = 200,
) -> WebhookDelivery:
    return WebhookDelivery(
        id=uuid.uuid4(),
        endpoint_id=endpoint.id,
        tenant_id=endpoint.tenant_id,
        event_type="task.completed",
        event_id=uuid.uuid4(),
        payload={"task_id": str(uuid.uuid4()), "status": "completed"},
        status=status,
        attempt_number=attempt_number,
        http_status_code=http_status_code,
        attempted_at=datetime.now(tz=UTC),
    )


# ---------------------------------------------------------------------------
# WebhookEndpoint CRUD
# ---------------------------------------------------------------------------


class TestWebhookEndpointCrud:
    def test_create_and_retrieve_endpoint(self, pg_session) -> None:
        """Creating an endpoint must persist a retrievable row."""
        repo = WebhookRepository(pg_session)
        ep = _make_endpoint()
        repo.create_endpoint(ep)
        pg_session.flush()

        retrieved = repo.get_endpoint(ep.id, tenant_id=TENANT_A)
        assert retrieved is not None
        assert retrieved.id == ep.id
        assert retrieved.url == "https://example.com/hook"
        assert retrieved.event_types == ["task.completed"]
        assert retrieved.is_active is True

    def test_get_endpoint_returns_none_for_missing(self, pg_session) -> None:
        repo = WebhookRepository(pg_session)
        result = repo.get_endpoint(uuid.uuid4(), tenant_id=TENANT_A)
        assert result is None

    def test_cross_tenant_isolation_on_get(self, pg_session) -> None:
        """An endpoint owned by tenant-A must not be retrievable by tenant-B."""
        repo = WebhookRepository(pg_session)
        ep = _make_endpoint(tenant_id=TENANT_A)
        repo.create_endpoint(ep)
        pg_session.flush()

        # Tenant-B must not see tenant-A's endpoint
        result = repo.get_endpoint(ep.id, tenant_id=TENANT_B)
        assert result is None

    def test_list_endpoints_scoped_to_tenant(self, pg_session) -> None:
        """list_endpoints must return only the calling tenant's endpoints."""
        repo = WebhookRepository(pg_session)
        ep_a1 = _make_endpoint(tenant_id=TENANT_A, url="https://a1.example.com/hook")
        ep_a2 = _make_endpoint(tenant_id=TENANT_A, url="https://a2.example.com/hook")
        ep_b = _make_endpoint(tenant_id=TENANT_B, url="https://b.example.com/hook")
        repo.create_endpoint(ep_a1)
        repo.create_endpoint(ep_a2)
        repo.create_endpoint(ep_b)
        pg_session.flush()

        results = repo.list_endpoints(TENANT_A)
        ids = {ep.id for ep in results}
        assert ep_a1.id in ids
        assert ep_a2.id in ids
        assert ep_b.id not in ids

    def test_list_endpoints_empty_for_new_tenant(self, pg_session) -> None:
        repo = WebhookRepository(pg_session)
        results = repo.list_endpoints(uuid.uuid4())
        assert results == []

    def test_disable_endpoint(self, pg_session) -> None:
        """disable_endpoint must set is_active=False and return True."""
        repo = WebhookRepository(pg_session)
        ep = _make_endpoint(tenant_id=TENANT_A)
        repo.create_endpoint(ep)
        pg_session.flush()

        updated = repo.disable_endpoint(ep.id, tenant_id=TENANT_A)
        pg_session.flush()
        pg_session.refresh(ep)

        assert updated is True
        assert ep.is_active is False

    def test_disable_endpoint_cross_tenant_no_effect(self, pg_session) -> None:
        """Disabling an endpoint with the wrong tenant must return False and not modify it."""
        repo = WebhookRepository(pg_session)
        ep = _make_endpoint(tenant_id=TENANT_A)
        repo.create_endpoint(ep)
        pg_session.flush()

        updated = repo.disable_endpoint(ep.id, tenant_id=TENANT_B)
        pg_session.flush()
        pg_session.refresh(ep)

        assert updated is False
        assert ep.is_active is True  # Unchanged

    def test_delete_endpoint(self, pg_session) -> None:
        """delete_endpoint must remove the row and return True."""
        repo = WebhookRepository(pg_session)
        ep = _make_endpoint(tenant_id=TENANT_A)
        repo.create_endpoint(ep)
        pg_session.flush()

        deleted = repo.delete_endpoint(ep.id, tenant_id=TENANT_A)
        pg_session.flush()

        assert deleted is True
        assert repo.get_endpoint(ep.id, tenant_id=TENANT_A) is None

    def test_delete_endpoint_returns_false_for_missing(self, pg_session) -> None:
        repo = WebhookRepository(pg_session)
        result = repo.delete_endpoint(uuid.uuid4(), tenant_id=TENANT_A)
        assert result is False

    def test_count_endpoints(self, pg_session) -> None:
        repo = WebhookRepository(pg_session)
        tenant_id = uuid.uuid4()
        repo.create_endpoint(_make_endpoint(tenant_id=tenant_id, url="https://c1.example.com/hook"))
        repo.create_endpoint(_make_endpoint(tenant_id=tenant_id, url="https://c2.example.com/hook"))
        pg_session.flush()

        assert repo.count_endpoints(tenant_id) == 2


# ---------------------------------------------------------------------------
# Event-type filtering with PostgreSQL ARRAY @> operator
# ---------------------------------------------------------------------------


class TestEventTypeFiltering:
    def test_active_endpoint_returned_for_subscribed_event(self, pg_session) -> None:
        """list_active_endpoints_for_event must return endpoints subscribed to the event."""
        repo = WebhookRepository(pg_session)
        tenant_id = uuid.uuid4()
        ep = _make_endpoint(
            tenant_id=tenant_id,
            event_types=["task.completed", "mission.failed"],
        )
        repo.create_endpoint(ep)
        pg_session.flush()

        results = repo.list_active_endpoints_for_event(tenant_id, "task.completed")
        assert any(e.id == ep.id for e in results)

    def test_inactive_endpoint_not_returned(self, pg_session) -> None:
        """Disabled endpoints must not appear in event-type queries."""
        repo = WebhookRepository(pg_session)
        tenant_id = uuid.uuid4()
        ep = _make_endpoint(tenant_id=tenant_id, is_active=False)
        repo.create_endpoint(ep)
        pg_session.flush()

        results = repo.list_active_endpoints_for_event(tenant_id, "task.completed")
        assert not any(e.id == ep.id for e in results)

    def test_endpoint_not_returned_for_unsubscribed_event(self, pg_session) -> None:
        """An endpoint subscribed to task.completed must not appear for mission.failed."""
        repo = WebhookRepository(pg_session)
        tenant_id = uuid.uuid4()
        ep = _make_endpoint(tenant_id=tenant_id, event_types=["task.completed"])
        repo.create_endpoint(ep)
        pg_session.flush()

        results = repo.list_active_endpoints_for_event(tenant_id, "mission.failed")
        assert not any(e.id == ep.id for e in results)

    def test_cross_tenant_event_isolation(self, pg_session) -> None:
        """Tenant-B's endpoints must not appear in tenant-A's event queries."""
        repo = WebhookRepository(pg_session)
        tenant_a = uuid.uuid4()
        tenant_b = uuid.uuid4()
        ep_b = _make_endpoint(tenant_id=tenant_b, event_types=["task.completed"])
        repo.create_endpoint(ep_b)
        pg_session.flush()

        results = repo.list_active_endpoints_for_event(tenant_a, "task.completed")
        assert not any(e.id == ep_b.id for e in results)


# ---------------------------------------------------------------------------
# WebhookDelivery — persistence and querying
# ---------------------------------------------------------------------------


class TestWebhookDeliveryPersistence:
    def test_record_delivery_persists_row(self, pg_session) -> None:
        """record_delivery must persist a retrievable WebhookDelivery row."""
        repo = WebhookRepository(pg_session)
        ep = _make_endpoint()
        repo.create_endpoint(ep)
        pg_session.flush()

        delivery = _make_delivery(ep, status="delivered")
        repo.record_delivery(delivery)
        pg_session.flush()

        retrieved = repo.get_delivery(delivery.id)
        assert retrieved is not None
        assert retrieved.id == delivery.id
        assert retrieved.status == "delivered"
        assert retrieved.http_status_code == 200

    def test_list_deliveries_ordered_newest_first(self, pg_session) -> None:
        """list_deliveries_for_endpoint must return newest deliveries first."""
        repo = WebhookRepository(pg_session)
        ep = _make_endpoint()
        repo.create_endpoint(ep)
        pg_session.flush()

        d1 = _make_delivery(ep, attempt_number=1)
        d2 = _make_delivery(ep, attempt_number=2)
        d3 = _make_delivery(ep, attempt_number=3)
        # Insert in order
        repo.record_delivery(d1)
        repo.record_delivery(d2)
        repo.record_delivery(d3)
        pg_session.flush()

        results = repo.list_deliveries_for_endpoint(ep.id, tenant_id=TENANT_A, limit=10)
        attempt_numbers = [d.attempt_number for d in results]
        # Newest first — attempt 3 should come before 1
        assert attempt_numbers.index(3) < attempt_numbers.index(1)

    def test_list_deliveries_cross_tenant_isolation(self, pg_session) -> None:
        """Deliveries for tenant-A's endpoint must not appear in tenant-B's query."""
        repo = WebhookRepository(pg_session)
        ep_a = _make_endpoint(tenant_id=TENANT_A)
        repo.create_endpoint(ep_a)
        pg_session.flush()

        delivery = _make_delivery(ep_a)
        repo.record_delivery(delivery)
        pg_session.flush()

        # Querying with tenant-B must return empty
        results = repo.list_deliveries_for_endpoint(ep_a.id, tenant_id=TENANT_B, limit=10)
        assert results == []

    def test_count_recent_failures_counts_only_failed(self, pg_session) -> None:
        """count_recent_failures must count only 'failed' status rows."""
        repo = WebhookRepository(pg_session)
        ep = _make_endpoint()
        repo.create_endpoint(ep)
        pg_session.flush()

        # 2 failures, 1 success
        repo.record_delivery(_make_delivery(ep, status="failed", attempt_number=1, http_status_code=500))
        repo.record_delivery(_make_delivery(ep, status="failed", attempt_number=2, http_status_code=503))
        repo.record_delivery(_make_delivery(ep, status="delivered", attempt_number=3, http_status_code=200))
        pg_session.flush()

        count = repo.count_recent_failures(ep.id, since_attempt=1)
        assert count == 2

    def test_count_recent_failures_respects_since_attempt(self, pg_session) -> None:
        """count_recent_failures(since_attempt=3) must not count attempts 1 and 2."""
        repo = WebhookRepository(pg_session)
        ep = _make_endpoint()
        repo.create_endpoint(ep)
        pg_session.flush()

        repo.record_delivery(_make_delivery(ep, status="failed", attempt_number=1, http_status_code=500))
        repo.record_delivery(_make_delivery(ep, status="failed", attempt_number=2, http_status_code=500))
        repo.record_delivery(_make_delivery(ep, status="failed", attempt_number=3, http_status_code=500))
        pg_session.flush()

        # Only attempt 3 and above
        count = repo.count_recent_failures(ep.id, since_attempt=3)
        assert count == 1

    def test_delivery_payload_stored_as_jsonb(self, pg_session) -> None:
        """The delivery payload must be stored and retrieved correctly as JSONB."""
        repo = WebhookRepository(pg_session)
        ep = _make_endpoint()
        repo.create_endpoint(ep)
        pg_session.flush()

        payload = {"task_id": "abc-123", "status": "completed", "nested": {"key": "value"}}
        delivery = WebhookDelivery(
            id=uuid.uuid4(),
            endpoint_id=ep.id,
            tenant_id=TENANT_A,
            event_type="task.completed",
            event_id=uuid.uuid4(),
            payload=payload,
            status="delivered",
            attempt_number=1,
            http_status_code=200,
            attempted_at=datetime.now(tz=UTC),
        )
        repo.record_delivery(delivery)
        pg_session.flush()

        retrieved = repo.get_delivery(delivery.id)
        assert retrieved is not None
        assert retrieved.payload["task_id"] == "abc-123"
        assert retrieved.payload["nested"]["key"] == "value"
