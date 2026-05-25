from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api.routes import observability as observability_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.auth.principal import Principal, PrincipalType
from backend.observability.metrics import MetricsSnapshot


def _build_app(tenant_id: uuid.UUID) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _inject_principal(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.principal = Principal(
            subject_id="test-user",
            tenant_id=str(tenant_id),
            principal_type=PrincipalType.USER,
            roles=("tenant_admin",),
        )
        return await call_next(request)

    app.include_router(observability_module.router, prefix="/v1")
    app.dependency_overrides[get_request_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_tenant_db_session] = lambda: MagicMock()
    return app


def test_tenant_reliability_summary_route_returns_read_only_projection() -> None:
    tenant_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    snapshot = MetricsSnapshot(
        tasks_queued=10,
        tasks_completed=30,
        tasks_failed=10,
        dead_letter_count=5,
        lease_expirations=8,
        active_leases=12,
        queued_tasks=10,
        worker_utilization=0.6,
        released_leases=7,
    )

    with patch(
        "backend.api.routes.observability.ObservabilityService.metrics_snapshot",
        return_value=snapshot,
    ) as metrics_snapshot:
        response = client.get("/v1/observability/reliability/summary")

    assert response.status_code == 200
    metrics_snapshot.assert_called_once_with(tenant_id=str(tenant_id))
    body = response.json()
    assert body["authority_class"] == "read_model"
    assert body["side_effect_class"] == "none"
    assert body["does_not_execute_runtime_work"] is True
    assert body["mission_throughput_total"] == 50
    assert body["mission_throughput_completed"] == 30
    assert body["mission_throughput_failed"] == 10
    assert body["mission_throughput_success_rate"] == 0.75
    assert body["dead_letter_rate"] == 0.1111
    assert body["lease_health"] == {
        "active_leases": 12,
        "expired_leases": 8,
        "released_leases": 7,
        "lease_expiration_rate": 0.4,
    }
    assert body["recovery"] == {
        "recovered_tasks": 3,
        "dead_lettered_tasks": 5,
        "recovery_success_ratio": 0.375,
    }


def test_tenant_reliability_summary_bounds_dead_letter_rate_when_only_dead_letters() -> None:
    tenant_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    snapshot = MetricsSnapshot(
        tasks_queued=0,
        tasks_completed=0,
        tasks_failed=0,
        dead_letter_count=5,
        lease_expirations=0,
        active_leases=0,
        queued_tasks=0,
        worker_utilization=0.0,
        released_leases=0,
    )

    with patch(
        "backend.api.routes.observability.ObservabilityService.metrics_snapshot",
        return_value=snapshot,
    ):
        response = client.get("/v1/observability/reliability/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["dead_letter_rate"] == 1.0
