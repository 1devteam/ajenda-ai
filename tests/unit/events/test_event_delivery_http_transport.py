from __future__ import annotations

import json
import uuid

import httpx

from backend.domain.enums import EventDeliveryState
from backend.domain.event_delivery import EventDelivery
from backend.services.event_delivery_http_transport import (
    HttpEventDeliveryTransport,
    HttpEventDeliveryTransportConfig,
)


def _delivery(headers: dict[str, str] | None = None) -> EventDelivery:
    return EventDelivery(
        id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        tenant_id="tenant-a",
        event_type="mission.completed",
        destination_url="https://example.test/webhooks/ajenda",
        status=EventDeliveryState.DELIVERING.value,
        payload_json={"mission_id": "mission-1"},
        headers_json=headers or {"X-Custom-Header": "custom-value"},
        idempotency_key="tenant-a:mission.completed:mission-1",
        attempts=1,
        max_attempts=3,
    )


def test_http_transport_posts_delivery_payload_and_headers() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204)

    transport = HttpEventDeliveryTransport(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        config=HttpEventDeliveryTransportConfig(user_agent="Ajenda-Test/1.0"),
    )

    result = transport.deliver(_delivery())

    assert result.succeeded is True
    assert result.error is None
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://example.test/webhooks/ajenda"
    assert request.headers["Content-Type"] == "application/json"
    assert request.headers["User-Agent"] == "Ajenda-Test/1.0"
    assert request.headers["X-Ajenda-Delivery-Id"] == "11111111-1111-1111-1111-111111111111"
    assert request.headers["X-Ajenda-Tenant-Id"] == "tenant-a"
    assert request.headers["X-Ajenda-Event-Type"] == "mission.completed"
    assert request.headers["X-Ajenda-Idempotency-Key"] == "tenant-a:mission.completed:mission-1"
    assert request.headers["X-Custom-Header"] == "custom-value"
    assert json.loads(request.content) == {"mission_id": "mission-1"}


def test_http_transport_prevents_custom_headers_from_overriding_reserved_headers() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204)

    delivery = _delivery(
        {
            "Content-Type": "text/plain",
            "User-Agent": "spoofed-agent",
            "X-Ajenda-Delivery-Id": "spoofed-delivery",
            "X-Ajenda-Tenant-Id": "spoofed-tenant",
            "X-Ajenda-Event-Type": "spoofed.event",
            "X-Ajenda-Idempotency-Key": "spoofed-key",
            "X-Custom-Header": "custom-value",
        }
    )
    transport = HttpEventDeliveryTransport(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        config=HttpEventDeliveryTransportConfig(user_agent="Ajenda-Test/1.0"),
    )

    result = transport.deliver(delivery)

    assert result.succeeded is True
    request = requests[0]
    assert request.headers["Content-Type"] == "application/json"
    assert request.headers["User-Agent"] == "Ajenda-Test/1.0"
    assert request.headers["X-Ajenda-Delivery-Id"] == "11111111-1111-1111-1111-111111111111"
    assert request.headers["X-Ajenda-Tenant-Id"] == "tenant-a"
    assert request.headers["X-Ajenda-Event-Type"] == "mission.completed"
    assert request.headers["X-Ajenda-Idempotency-Key"] == "tenant-a:mission.completed:mission-1"
    assert request.headers["X-Custom-Header"] == "custom-value"


def test_http_transport_strips_case_insensitive_reserved_header_collisions() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204)

    delivery = _delivery(
        {
            "content-type": "text/plain",
            "user-agent": "spoofed-agent",
            "x-ajenda-delivery-id": "spoofed-delivery",
            "x-ajenda-tenant-id": "spoofed-tenant",
            "x-ajenda-event-type": "spoofed.event",
            "x-ajenda-idempotency-key": "spoofed-key",
            "X-Custom-Header": "custom-value",
        }
    )
    transport = HttpEventDeliveryTransport(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        config=HttpEventDeliveryTransportConfig(user_agent="Ajenda-Test/1.0"),
    )

    result = transport.deliver(delivery)

    assert result.succeeded is True
    request = requests[0]
    assert request.headers.get_list("content-type") == ["application/json"]
    assert request.headers.get_list("user-agent") == ["Ajenda-Test/1.0"]
    assert request.headers.get_list("x-ajenda-delivery-id") == [
        "11111111-1111-1111-1111-111111111111"
    ]
    assert request.headers.get_list("x-ajenda-tenant-id") == ["tenant-a"]
    assert request.headers.get_list("x-ajenda-event-type") == ["mission.completed"]
    assert request.headers.get_list("x-ajenda-idempotency-key") == [
        "tenant-a:mission.completed:mission-1"
    ]
    assert request.headers["X-Custom-Header"] == "custom-value"


def test_http_transport_applies_configured_timeout_to_injected_client() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204)

    transport = HttpEventDeliveryTransport(
        client=httpx.Client(timeout=None, transport=httpx.MockTransport(handler)),
        config=HttpEventDeliveryTransportConfig(timeout_seconds=17.5),
    )

    result = transport.deliver(_delivery())

    assert result.succeeded is True
    request = requests[0]
    assert request.extensions["timeout"] == {
        "connect": 17.5,
        "read": 17.5,
        "write": 17.5,
        "pool": 17.5,
    }


def test_http_transport_treats_non_2xx_response_as_failure() -> None:
    transport = HttpEventDeliveryTransport(
        client=httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(503)))
    )

    result = transport.deliver(_delivery())

    assert result.succeeded is False
    assert result.error == "HTTP delivery returned status 503"


def test_http_transport_treats_timeout_as_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connection timed out", request=request)

    transport = HttpEventDeliveryTransport(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    result = transport.deliver(_delivery())

    assert result.succeeded is False
    assert result.error is not None
    assert result.error.startswith("HTTP delivery timed out:")


def test_http_transport_treats_request_error_as_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    transport = HttpEventDeliveryTransport(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    result = transport.deliver(_delivery())

    assert result.succeeded is False
    assert result.error is not None
    assert result.error.startswith("HTTP delivery failed:")
