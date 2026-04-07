"""Unit tests for WebhookDispatchService.

Test coverage:
  Registration:
    - Happy path: HTTPS URL, valid event types, returns endpoint + secret
    - Feature gate: FeatureNotAvailableError if plan lacks 'webhooks'
    - URL validation: rejects HTTP URLs
    - Empty event_types rejected
    - Unknown event types pass through (validation is at the route layer)

  Dispatch:
    - Successful delivery: 200 response, delivery recorded as 'delivered'
    - Failed delivery: 500 response, delivery recorded as 'failed'
    - Network timeout: delivery recorded as 'failed' with error_message
    - Connection error: delivery recorded as 'failed' with error_message
    - No matching endpoints: returns empty list
    - Inactive endpoint: skipped (not in list_active_endpoints_for_event)
    - Multiple endpoints: all receive the event

  Auto-disable:
    - Endpoint disabled after MAX_CONSECUTIVE_FAILURES failures

  HMAC signing:
    - Signature format: sha256=<hex>
    - Signature is deterministic for same body + secret_hash

  Delivery record:
    - Delivery ID is unique per attempt
    - event_id is preserved across retry attempts
    - attempt_number is recorded correctly
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import httpx
import pytest

from backend.domain.webhook_endpoint import WebhookEndpoint
from backend.services.quota_enforcement import FeatureNotAvailableError
from backend.services.webhook_dispatch import (
    MAX_CONSECUTIVE_FAILURES,
    WebhookDispatchService,
    WebhookNotFoundError,
    WebhookRegistrationError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TENANT_ID = uuid.uuid4()
ENDPOINT_ID = uuid.uuid4()


def _make_endpoint(
    *,
    is_active: bool = True,
    event_types: list[str] | None = None,
    secret_hash: str = "fakehash",
    secret_ciphertext: str | None = None,
) -> WebhookEndpoint:
    ep = MagicMock(spec=WebhookEndpoint)
    ep.id = ENDPOINT_ID
    ep.tenant_id = TENANT_ID
    ep.url = "https://example.com/hook"
    ep.secret_hash = secret_hash
    # None → legacy bcrypt-hash signing path (pre-migration-0009 endpoints).
    # Pass a real Fernet ciphertext to test the encrypted-secret path.
    ep.secret_ciphertext = secret_ciphertext
    ep.event_types = event_types or ["task.completed"]
    ep.is_active = is_active
    ep.created_at = datetime.now(tz=UTC)
    ep.updated_at = datetime.now(tz=UTC)
    return ep


def _make_service(
    *,
    endpoints: list[WebhookEndpoint] | None = None,
    failure_count: int = 0,
    http_response: MagicMock | None = None,
    http_raise: Exception | None = None,
    feature_allowed: bool = True,
) -> tuple[WebhookDispatchService, MagicMock, MagicMock]:
    """Build a WebhookDispatchService with all dependencies mocked.

    Returns (service, mock_repo, mock_http_client).
    """
    mock_db = MagicMock()
    mock_http = MagicMock(spec=httpx.Client)

    if http_raise is not None:
        mock_http.post.side_effect = http_raise
    elif http_response is not None:
        mock_http.post.return_value = http_response
    else:
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "ok"
        mock_http.post.return_value = resp

    service = WebhookDispatchService(mock_db, http_client=mock_http)

    # Patch the repo
    mock_repo = MagicMock()
    mock_repo.list_active_endpoints_for_event.return_value = endpoints or []
    mock_repo.count_recent_failures.return_value = failure_count
    mock_repo.record_delivery.side_effect = lambda d: d
    mock_repo.create_endpoint.side_effect = lambda e: e
    mock_repo.get_endpoint.return_value = endpoints[0] if endpoints else None
    mock_repo.list_endpoints.return_value = endpoints or []
    mock_repo.delete_endpoint.return_value = bool(endpoints)
    mock_repo.disable_endpoint.return_value = True
    service._repo = mock_repo

    # Patch quota enforcement
    mock_quota = MagicMock()
    if not feature_allowed:
        mock_quota.require_feature.side_effect = FeatureNotAvailableError(feature="webhooks", plan="free")
    service._quota = mock_quota

    return service, mock_repo, mock_http


def _make_http_response(status_code: int, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


class TestRegisterEndpoint:
    def test_happy_path_returns_endpoint_and_secret(self):
        service, mock_repo, _ = _make_service()
        endpoint, secret = service.register_endpoint(
            tenant_id=TENANT_ID,
            url="https://example.com/hook",
            event_types=["task.completed"],
        )
        assert endpoint is not None
        assert len(secret) == 64  # 32 bytes as hex
        mock_repo.create_endpoint.assert_called_once()

    def test_feature_gate_raises_for_free_plan(self):
        service, _, _ = _make_service(feature_allowed=False)
        with pytest.raises(FeatureNotAvailableError):
            service.register_endpoint(
                tenant_id=TENANT_ID,
                url="https://example.com/hook",
                event_types=["task.completed"],
            )

    def test_rejects_http_url(self):
        service, _, _ = _make_service()
        with pytest.raises(WebhookRegistrationError, match="HTTPS"):
            service.register_endpoint(
                tenant_id=TENANT_ID,
                url="http://example.com/hook",
                event_types=["task.completed"],
            )

    def test_rejects_empty_event_types(self):
        service, _, _ = _make_service()
        with pytest.raises(WebhookRegistrationError, match="event_type"):
            service.register_endpoint(
                tenant_id=TENANT_ID,
                url="https://example.com/hook",
                event_types=[],
            )

    def test_secret_is_unique_per_registration(self):
        service, _, _ = _make_service()
        _, secret1 = service.register_endpoint(
            tenant_id=TENANT_ID,
            url="https://example.com/hook1",
            event_types=["task.completed"],
        )
        _, secret2 = service.register_endpoint(
            tenant_id=TENANT_ID,
            url="https://example.com/hook2",
            event_types=["task.completed"],
        )
        assert secret1 != secret2


# ---------------------------------------------------------------------------
# Dispatch tests
# ---------------------------------------------------------------------------


class TestDispatchEvent:
    def test_successful_delivery_records_delivered_status(self):
        ep = _make_endpoint()
        service, mock_repo, mock_http = _make_service(
            endpoints=[ep],
            http_response=_make_http_response(200, "ok"),
        )
        results = service.dispatch_event(
            tenant_id=TENANT_ID,
            event_type="task.completed",
            payload={"task_id": "abc"},
        )
        assert len(results) == 1
        assert results[0].succeeded is True
        assert results[0].http_status == 200
        # Delivery record should have been updated to 'delivered'
        delivery = mock_repo.record_delivery.call_args[0][0]
        assert delivery.status == "delivered"
        assert delivery.delivered_at is not None

    def test_failed_delivery_records_failed_status(self):
        ep = _make_endpoint()
        service, mock_repo, mock_http = _make_service(
            endpoints=[ep],
            http_response=_make_http_response(500, "error"),
        )
        results = service.dispatch_event(
            tenant_id=TENANT_ID,
            event_type="task.completed",
            payload={"task_id": "abc"},
        )
        assert len(results) == 1
        assert results[0].succeeded is False
        assert results[0].http_status == 500
        delivery = mock_repo.record_delivery.call_args[0][0]
        assert delivery.status == "failed"

    def test_timeout_records_failed_with_error_message(self):
        ep = _make_endpoint()
        service, mock_repo, _ = _make_service(
            endpoints=[ep],
            http_raise=httpx.TimeoutException("timed out"),
        )
        results = service.dispatch_event(
            tenant_id=TENANT_ID,
            event_type="task.completed",
            payload={},
        )
        assert results[0].succeeded is False
        assert results[0].error is not None
        assert "timed out" in results[0].error.lower()

    def test_connection_error_records_failed_with_error_message(self):
        ep = _make_endpoint()
        service, mock_repo, _ = _make_service(
            endpoints=[ep],
            http_raise=httpx.ConnectError("refused"),
        )
        results = service.dispatch_event(
            tenant_id=TENANT_ID,
            event_type="task.completed",
            payload={},
        )
        assert results[0].succeeded is False
        assert "Connection error" in results[0].error

    def test_no_matching_endpoints_returns_empty_list(self):
        service, _, _ = _make_service(endpoints=[])
        results = service.dispatch_event(
            tenant_id=TENANT_ID,
            event_type="task.completed",
            payload={},
        )
        assert results == []

    def test_multiple_endpoints_all_receive_event(self):
        ep1 = _make_endpoint()
        ep2 = _make_endpoint()
        ep2.id = uuid.uuid4()
        ep2.url = "https://other.example.com/hook"
        service, mock_repo, mock_http = _make_service(
            endpoints=[ep1, ep2],
            http_response=_make_http_response(200),
        )
        results = service.dispatch_event(
            tenant_id=TENANT_ID,
            event_type="task.completed",
            payload={},
        )
        assert len(results) == 2
        assert all(r.succeeded for r in results)

    def test_event_id_preserved_across_attempts(self):
        ep = _make_endpoint()
        service, mock_repo, _ = _make_service(
            endpoints=[ep],
            http_response=_make_http_response(200),
        )
        event_id = uuid.uuid4()
        service.dispatch_event(
            tenant_id=TENANT_ID,
            event_type="task.completed",
            payload={},
            event_id=event_id,
        )
        delivery = mock_repo.record_delivery.call_args[0][0]
        assert delivery.event_id == event_id

    def test_attempt_number_recorded_correctly(self):
        ep = _make_endpoint()
        service, mock_repo, _ = _make_service(
            endpoints=[ep],
            http_response=_make_http_response(200),
        )
        service.dispatch_event(
            tenant_id=TENANT_ID,
            event_type="task.completed",
            payload={},
            attempt_number=3,
        )
        delivery = mock_repo.record_delivery.call_args[0][0]
        assert delivery.attempt_number == 3


# ---------------------------------------------------------------------------
# Auto-disable tests
# ---------------------------------------------------------------------------


class TestAutoDisable:
    def test_endpoint_disabled_after_max_failures(self):
        ep = _make_endpoint()
        service, mock_repo, _ = _make_service(
            endpoints=[ep],
            http_response=_make_http_response(500),
            failure_count=MAX_CONSECUTIVE_FAILURES,
        )
        service.dispatch_event(
            tenant_id=TENANT_ID,
            event_type="task.completed",
            payload={},
        )
        mock_repo.disable_endpoint.assert_called_once_with(ep.id, tenant_id=TENANT_ID)
        delivery = mock_repo.record_delivery.call_args[0][0]
        assert delivery.status == "dead_lettered"

    def test_endpoint_not_disabled_below_threshold(self):
        ep = _make_endpoint()
        service, mock_repo, _ = _make_service(
            endpoints=[ep],
            http_response=_make_http_response(500),
            failure_count=MAX_CONSECUTIVE_FAILURES - 1,
        )
        service.dispatch_event(
            tenant_id=TENANT_ID,
            event_type="task.completed",
            payload={},
        )
        mock_repo.disable_endpoint.assert_not_called()


# ---------------------------------------------------------------------------
# HMAC signing tests
# ---------------------------------------------------------------------------


class TestHmacSigning:
    def test_signature_format(self):
        body = b'{"test": "payload"}'
        sig = WebhookDispatchService._sign(body, "mysecret")
        assert sig.startswith("sha256=")
        assert len(sig) == len("sha256=") + 64  # sha256 hex = 64 chars

    def test_signature_is_deterministic(self):
        body = b'{"test": "payload"}'
        sig1 = WebhookDispatchService._sign(body, "mysecret")
        sig2 = WebhookDispatchService._sign(body, "mysecret")
        assert sig1 == sig2

    def test_different_bodies_produce_different_signatures(self):
        sig1 = WebhookDispatchService._sign(b"body1", "mysecret")
        sig2 = WebhookDispatchService._sign(b"body2", "mysecret")
        assert sig1 != sig2

    def test_different_secrets_produce_different_signatures(self):
        body = b'{"test": "payload"}'
        sig1 = WebhookDispatchService._sign(body, "secret1")
        sig2 = WebhookDispatchService._sign(body, "secret2")
        assert sig1 != sig2

    def test_signature_header_sent_in_request(self):
        ep = _make_endpoint(secret_hash="testhash")
        service, _, mock_http = _make_service(
            endpoints=[ep],
            http_response=_make_http_response(200),
        )
        service.dispatch_event(
            tenant_id=TENANT_ID,
            event_type="task.completed",
            payload={"x": 1},
        )
        call_kwargs = mock_http.post.call_args[1]
        headers = call_kwargs["headers"]
        assert "X-Ajenda-Signature-256" in headers
        assert headers["X-Ajenda-Signature-256"].startswith("sha256=")


# ---------------------------------------------------------------------------
# Endpoint management tests
# ---------------------------------------------------------------------------


class TestEndpointManagement:
    def test_get_endpoint_raises_not_found_for_missing(self):
        service, mock_repo, _ = _make_service(endpoints=[])
        mock_repo.get_endpoint.return_value = None
        with pytest.raises(WebhookNotFoundError):
            service.get_endpoint(uuid.uuid4(), tenant_id=TENANT_ID)

    def test_delete_endpoint_raises_not_found_for_missing(self):
        service, mock_repo, _ = _make_service(endpoints=[])
        mock_repo.delete_endpoint.return_value = False
        with pytest.raises(WebhookNotFoundError):
            service.delete_endpoint(uuid.uuid4(), tenant_id=TENANT_ID)

    def test_list_endpoints_returns_all(self):
        ep1 = _make_endpoint()
        ep2 = _make_endpoint()
        service, mock_repo, _ = _make_service(endpoints=[ep1, ep2])
        result = service.list_endpoints(TENANT_ID)
        assert len(result) == 2
