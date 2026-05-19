from __future__ import annotations

from dataclasses import dataclass

import httpx

from backend.domain.event_delivery import EventDelivery
from backend.services.event_delivery_dispatcher import EventDeliveryTransportResult


@dataclass(frozen=True, slots=True)
class HttpEventDeliveryTransportConfig:
    timeout_seconds: float = 10.0
    user_agent: str = "Ajenda-Event-Delivery/1.0"


class HttpEventDeliveryTransport:
    """HTTP implementation of the event delivery transport boundary."""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        config: HttpEventDeliveryTransportConfig | None = None,
    ) -> None:
        self._client = client
        self._config = config or HttpEventDeliveryTransportConfig()

    def deliver(self, delivery: EventDelivery) -> EventDeliveryTransportResult:
        headers = self._build_headers(delivery)
        try:
            response = self._post(
                delivery.destination_url,
                headers=headers,
                json=delivery.payload_json,
            )
        except httpx.TimeoutException as exc:
            return EventDeliveryTransportResult.failure(f"HTTP delivery timed out: {exc}")
        except httpx.RequestError as exc:
            return EventDeliveryTransportResult.failure(f"HTTP delivery failed: {exc}")

        if 200 <= response.status_code < 300:
            return EventDeliveryTransportResult.success()

        return EventDeliveryTransportResult.failure(
            f"HTTP delivery returned status {response.status_code}"
        )

    def _post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
    ) -> httpx.Response:
        if self._client is not None:
            return self._client.post(url, headers=headers, json=json)

        with httpx.Client(timeout=self._config.timeout_seconds) as client:
            return client.post(url, headers=headers, json=json)

    def _build_headers(self, delivery: EventDelivery) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": self._config.user_agent,
            "X-Ajenda-Delivery-Id": str(delivery.id),
            "X-Ajenda-Tenant-Id": delivery.tenant_id,
            "X-Ajenda-Event-Type": delivery.event_type,
            "X-Ajenda-Idempotency-Key": delivery.idempotency_key,
        }
        headers.update(delivery.headers_json or {})
        return headers
