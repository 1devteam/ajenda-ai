from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api.routes.operations import router
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.auth.principal import Principal, PrincipalType


class _InspectionOpsService:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def inspect_dead_letter(self, **kwargs):
        self.calls.append(kwargs)
        return [
            {
                "task_id": str(uuid.uuid4()),
                "mission_id": str(uuid.uuid4()),
                "status": "dead_lettered",
            }
        ]


class _EmptyInspectionOpsService:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def inspect_dead_letter(self, **kwargs):
        self.calls.append(kwargs)
        return []


def _build_client(monkeypatch, service: object, *, tenant_id: uuid.UUID | None = None) -> TestClient:
    app = FastAPI()
    request_tenant_id = tenant_id or uuid.uuid4()

    @app.middleware("http")
    async def _inject_principal(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.principal = Principal("viewer", str(request_tenant_id), PrincipalType.USER, roles=("viewer",))
        return await call_next(request)

    app.include_router(router, prefix="/v1")

    def _tenant_dep() -> uuid.UUID:
        return request_tenant_id

    def _db_dep():
        yield MagicMock()

    def _queue_dep():
        return MagicMock()

    app.dependency_overrides[get_request_tenant_id] = _tenant_dep
    app.dependency_overrides[get_tenant_db_session] = _db_dep
    app.dependency_overrides[get_queue_adapter] = _queue_dep

    monkeypatch.setattr(
        "backend.api.routes.operations.OperationsService",
        lambda *_args, **_kwargs: service,
    )
    return TestClient(app, raise_server_exceptions=False)


def test_dead_letter_inspection_route_returns_tenant_scoped_payload(monkeypatch) -> None:
    service = _InspectionOpsService()
    client = _build_client(monkeypatch, service)
    response = client.get("/v1/operations/dead-letter")

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert payload[0]["status"] == "dead_lettered"
    assert "task_id" in payload[0]
    assert "mission_id" in payload[0]
    assert len(service.calls) == 1
    assert uuid.UUID(service.calls[0]["tenant_id"])


def test_dead_letter_inspection_route_returns_empty_payload_when_no_dead_letter_rows_exist(monkeypatch) -> None:
    service = _EmptyInspectionOpsService()
    client = _build_client(monkeypatch, service)
    response = client.get("/v1/operations/dead-letter")

    assert response.status_code == 200
    assert response.json() == []
    assert len(service.calls) == 1
    assert uuid.UUID(service.calls[0]["tenant_id"])


def test_dead_letter_inspection_route_passes_request_tenant_to_service(monkeypatch) -> None:
    service = _InspectionOpsService()
    tenant_id = uuid.uuid4()
    client = _build_client(monkeypatch, service, tenant_id=tenant_id)
    response = client.get("/v1/operations/dead-letter")

    assert response.status_code == 200
    assert service.calls == [{"tenant_id": str(tenant_id)}]
