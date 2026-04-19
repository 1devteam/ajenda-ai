from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.operations import router
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter


class _InspectionOpsService:
    def inspect_dead_letter(self, **_kwargs):
        return [
            {
                "task_id": str(uuid.uuid4()),
                "mission_id": str(uuid.uuid4()),
                "status": "dead_lettered",
            }
        ]


def test_dead_letter_inspection_route_returns_tenant_scoped_payload(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(router, prefix="/v1")

    def _tenant_dep() -> uuid.UUID:
        return uuid.uuid4()

    def _db_dep():
        yield MagicMock()

    def _queue_dep():
        return MagicMock()

    app.dependency_overrides[get_request_tenant_id] = _tenant_dep
    app.dependency_overrides[get_tenant_db_session] = _db_dep
    app.dependency_overrides[get_queue_adapter] = _queue_dep

    monkeypatch.setattr(
        "backend.api.routes.operations.OperationsService",
        lambda *_args, **_kwargs: _InspectionOpsService(),
    )

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/v1/operations/dead-letter")

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert payload[0]["status"] == "dead_lettered"
    assert "task_id" in payload[0]
    assert "mission_id" in payload[0]
