from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api.routes import light_crm as light_crm_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.auth.principal import Principal, PrincipalType


def _build_app(tenant_id: uuid.UUID) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _inject_principal(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.principal = Principal(
            subject_id="test-user",
            tenant_id=str(tenant_id),
            principal_type=PrincipalType.USER,
            roles=("tenant_operator",),
        )
        return await call_next(request)

    app.include_router(light_crm_module.router, prefix="/v1")

    def _override_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_db() -> MagicMock:
        return MagicMock()

    app.dependency_overrides[get_request_tenant_id] = _override_tenant_id
    app.dependency_overrides[get_tenant_db_session] = _override_db
    return app


def test_list_crm_records_returns_items() -> None:
    tenant_id = uuid.uuid4()
    client = TestClient(_build_app(tenant_id))

    with patch("backend.api.routes.light_crm.LightCrmRecordService") as service_cls:
        service = MagicMock()
        service_cls.return_value = service
        service.list_records.return_value = [{"id": "contact-1", "email": "ops@example.com"}]

        response = client.get("/v1/crm/records", params={"record_type": "contact"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["record_type"] == "contact"
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == "contact-1"


def test_upsert_crm_record_uses_workflow_helper() -> None:
    tenant_id = uuid.uuid4()
    client = TestClient(_build_app(tenant_id))

    with patch("backend.services.light_crm.workflow.complete_internal_crm_upsert") as mock_upsert:
        mock_upsert.return_value = {"id": "contact-9", "email": "buyer@example.com"}

        response = client.put(
            "/v1/crm/records/contact/contact-9",
            json={"data": {"email": "buyer@example.com"}},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "contact-9"
    mock_upsert.assert_called_once()


def test_light_crm_http_uses_tenant_session_and_skips_gtm_quota() -> None:
    import inspect

    source = inspect.getsource(light_crm_module)
    assert "get_tenant_db_session" in source
    assert "get_db_session" not in source
    assert "require_feature" not in source
    assert "QuotaEnforcementService" not in source
