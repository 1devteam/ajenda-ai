from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.plugins import router as plugins_router


def test_list_plugins_endpoint() -> None:
    app = FastAPI()
    app.include_router(plugins_router, prefix="/v1")
    client = TestClient(app)

    response = client.get("/v1/plugins")
    assert response.status_code == 200
    body = response.json()
    assert body["central_brain_plugin_id"] == "ajenda-brain"
    plugin_ids = {item["plugin_id"] for item in body["plugins"]}
    assert "ajenda-brain" in plugin_ids
    assert "hubspot-crm" in plugin_ids


def test_get_plugin_by_id() -> None:
    app = FastAPI()
    app.include_router(plugins_router, prefix="/v1")
    client = TestClient(app)

    response = client.get("/v1/plugins/smtp-email")
    assert response.status_code == 200
    assert response.json()["integration_types"] == ["smtp"]
