from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from services.hubspot_crm_adapter.hubspot import HubSpotApiError, HubSpotClient, bearer_token_from_header
from services.hubspot_crm_adapter.main import app

TOKEN = "test-hubspot-token"


def _mock_response(*, status_code: int, json_body: object) -> httpx.Response:
    request = httpx.Request("POST", "https://api.hubapi.com/crm/v3/objects/contacts/search")
    return httpx.Response(status_code=status_code, json=json_body, request=request)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["adapter"] == "hubspot-crm"


def test_search_requires_bearer(client: TestClient) -> None:
    response = client.get("/v1/search?company=Acme")
    assert response.status_code == 401


def test_search_by_company(client: TestClient) -> None:
    hubspot_payload = {
        "results": [
            {
                "id": "123",
                "properties": {"name": "Acme Corp", "domain": "acme.com"},
            }
        ]
    }
    with patch("services.hubspot_crm_adapter.hubspot.httpx.Client") as client_cls:
        http_client = MagicMock()
        client_cls.return_value.__enter__.return_value = http_client
        http_client.request.return_value = _mock_response(status_code=200, json_body=hubspot_payload)

        response = client.get(
            "/v1/search",
            params={"company": "Acme"},
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["object_type"] == "companies"
    assert body["source"] == "hubspot"
    call_kwargs = http_client.request.call_args.kwargs
    assert call_kwargs["json"]["filterGroups"][0]["filters"][0]["propertyName"] == "name"


def test_search_by_domain(client: TestClient) -> None:
    with patch("services.hubspot_crm_adapter.hubspot.httpx.Client") as client_cls:
        http_client = MagicMock()
        client_cls.return_value.__enter__.return_value = http_client
        http_client.request.return_value = _mock_response(status_code=200, json_body={"results": []})

        response = client.get(
            "/v1/search",
            params={"domain": "acme.com"},
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

    assert response.status_code == 200
    call_kwargs = http_client.request.call_args.kwargs
    assert call_kwargs["json"]["filterGroups"][0]["filters"][0]["propertyName"] == "domain"


def test_upsert_creates_contact(client: TestClient) -> None:
    search_response = _mock_response(status_code=200, json_body={"results": []})
    create_response = _mock_response(
        status_code=201,
        json_body={"id": "999", "properties": {"email": "buyer@example.com"}},
    )
    with patch("services.hubspot_crm_adapter.hubspot.httpx.Client") as client_cls:
        http_client = MagicMock()
        client_cls.return_value.__enter__.return_value = http_client
        http_client.request.side_effect = [search_response, create_response]

        response = client.post(
            "/v1/upsert",
            json={
                "record_type": "contact",
                "data": {"email": "buyer@example.com", "firstname": "Jane"},
            },
            headers={"Authorization": f"Bearer {TOKEN}", "Idempotency-Key": "idem-1"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "999"
    assert body["created"] is True
    assert body["hubspot_object_type"] == "contacts"


def test_upsert_updates_existing_contact(client: TestClient) -> None:
    search_response = _mock_response(
        status_code=200,
        json_body={"results": [{"id": "555", "properties": {"email": "buyer@example.com"}}]},
    )
    patch_response = _mock_response(
        status_code=200,
        json_body={"id": "555", "properties": {"email": "buyer@example.com", "firstname": "Jane"}},
    )
    with patch("services.hubspot_crm_adapter.hubspot.httpx.Client") as client_cls:
        http_client = MagicMock()
        client_cls.return_value.__enter__.return_value = http_client
        http_client.request.side_effect = [search_response, patch_response]

        response = client.post(
            "/v1/upsert",
            json={
                "record_type": "lead",
                "data": {"email": "buyer@example.com", "firstname": "Jane"},
            },
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "555"
    assert body["created"] is False


def test_upsert_rejects_unknown_record_type(client: TestClient) -> None:
    response = client.post(
        "/v1/upsert",
        json={"record_type": "ticket", "data": {"subject": "x"}},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 400


def test_hubspot_client_maps_api_errors() -> None:
    with patch("services.hubspot_crm_adapter.hubspot.httpx.Client") as client_cls:
        http_client = MagicMock()
        client_cls.return_value.__enter__.return_value = http_client
        http_client.request.return_value = httpx.Response(
            status_code=403,
            text="forbidden",
            request=httpx.Request("GET", "https://api.hubapi.com/crm/v3/objects/contacts"),
        )
        hubspot = HubSpotClient(access_token=TOKEN)
        with pytest.raises(HubSpotApiError) as exc_info:
            hubspot._request(method="GET", path="/crm/v3/objects/contacts")
        assert exc_info.value.status_code == 403


def test_bearer_token_from_header() -> None:
    assert bearer_token_from_header("Bearer abc") == "abc"
    with pytest.raises(ValueError, match="Bearer"):
        bearer_token_from_header("Token abc")
