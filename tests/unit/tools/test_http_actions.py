from __future__ import annotations

import socket
import uuid
from typing import Any

import httpx
import pytest

from backend.services.tools.http_actions import (
    http_request,
    validate_safe_http_url,
    vet_safe_http_destination,
)
from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation

PUBLIC_ADDR = "93.184.216.34"
PRIVATE_ADDR = "10.0.0.4"


def _context() -> ActionRuntimeContext:
    return ActionRuntimeContext(
        tenant_id=str(uuid.uuid4()),
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        worker_id="worker",
        lease_id=str(uuid.uuid4()),
    )


class _FakeResponse:
    def __init__(self, *, text: str = "ok", status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code
        self.headers = {"content-type": "text/plain"}


class _FakeClient:
    instances: list[_FakeClient] = []
    response_text = "ok"

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.requests: list[dict[str, Any]] = []
        _FakeClient.instances.append(self)

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def request(self, method: str, url: str, **kwargs: Any) -> _FakeResponse:
        self.requests.append({"method": method, "url": url, **kwargs})
        return _FakeResponse(text=self.response_text)


@pytest.fixture(autouse=True)
def reset_fake_client() -> None:
    _FakeClient.instances = []
    _FakeClient.response_text = "ok"


def _public_dns(host: str, port: int | None = None, *args: Any, **kwargs: Any) -> list[tuple[Any, ...]]:
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_ADDR, port or 443))]


def test_http_url_validation_allows_public_https_with_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("socket.getaddrinfo", _public_dns)

    assert (
        validate_safe_http_url("https://example.com/path", allowed_hosts=["example.com"]) == "https://example.com/path"
    )


def test_http_url_validation_rejects_http_scheme() -> None:
    with pytest.raises(ValueError, match="only allows https"):
        validate_safe_http_url("http://example.com")


def test_http_url_validation_rejects_missing_hostname() -> None:
    with pytest.raises(ValueError, match="hostname"):
        validate_safe_http_url("https:///status")


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost/status",
        "https://localhost.localdomain/status",
        "https://service.local/status",
        "https://internal-api.example.com/status",
        "https://169.254.169.254.example.com/status",
    ],
)
def test_http_url_validation_blocks_localhost_and_internal_hostnames(url: str) -> None:
    with pytest.raises(ValueError, match=r"http\.request"):
        validate_safe_http_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/status",
        "https://10.1.2.3/status",
        "https://172.16.0.1/status",
        "https://192.168.1.10/status",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/status",
        "https://[fc00::1]/status",
    ],
)
def test_http_url_validation_blocks_private_ip_literals(url: str) -> None:
    with pytest.raises(ValueError, match="private IP literal"):
        validate_safe_http_url(url)


def test_http_url_validation_blocks_private_dns_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "socket.getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PRIVATE_ADDR, 443))]
    )

    with pytest.raises(ValueError, match="private DNS"):
        validate_safe_http_url("https://example.com")


def test_http_url_validation_fails_closed_on_dns_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_dns(*args: Any, **kwargs: Any) -> list[tuple[Any, ...]]:
        raise socket.gaierror("not found")

    monkeypatch.setattr("socket.getaddrinfo", fail_dns)

    with pytest.raises(ValueError, match="DNS resolution failed"):
        validate_safe_http_url("https://example.com")


def test_http_url_validation_requires_public_routable_dns_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("socket.getaddrinfo", lambda *args, **kwargs: [])

    with pytest.raises(ValueError, match="public routable"):
        validate_safe_http_url("https://example.com")


def test_http_url_validation_keeps_allowed_hosts_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("socket.getaddrinfo", _public_dns)

    with pytest.raises(ValueError, match="allowed_hosts"):
        validate_safe_http_url("https://example.com/path", allowed_hosts=["api.example.com"])

    destination = vet_safe_http_destination("https://example.com/path", allowed_hosts=["EXAMPLE.COM."])
    assert destination.original_url == "https://example.com/path"
    assert str(destination.pinned_ip) == PUBLIC_ADDR


def test_http_request_uses_pinned_vetted_address_for_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    resolutions = [PUBLIC_ADDR, PRIVATE_ADDR]

    def rebinding_dns(host: str, port: int | None = None, *args: Any, **kwargs: Any) -> list[tuple[Any, ...]]:
        address = resolutions.pop(0) if resolutions else PRIVATE_ADDR
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port or 443))]

    monkeypatch.setattr("socket.getaddrinfo", rebinding_dns)
    monkeypatch.setattr("backend.services.network_egress.httpx.Client", _FakeClient)

    result = http_request(
        ToolInvocation(action="http.request", input={"method": "GET", "url": "https://example.com/path?q=1"}),
        _context(),
    )

    request = _FakeClient.instances[0].requests[0]
    assert request["url"] == f"https://{PUBLIC_ADDR}/path?q=1"
    assert request["headers"]["Host"] == "example.com"
    assert request["extensions"] == {"sni_hostname": "example.com"}
    assert result.output["url"] == "https://example.com/path?q=1"
    assert resolutions == [PRIVATE_ADDR]


def test_http_request_overrides_payload_host_header_with_original_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("socket.getaddrinfo", _public_dns)
    monkeypatch.setattr("backend.services.network_egress.httpx.Client", _FakeClient)

    http_request(
        ToolInvocation(
            action="http.request",
            input={
                "method": "GET",
                "url": "https://example.com:8443/path",
                "headers": {"host": "attacker.example", "connection": "keep-alive", "x-test": "ok"},
            },
        ),
        _context(),
    )

    request = _FakeClient.instances[0].requests[0]
    assert request["headers"] == {"x-test": "ok", "Host": "example.com:8443", "Connection": "close"}


def test_http_request_keeps_redirects_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("socket.getaddrinfo", _public_dns)
    monkeypatch.setattr("backend.services.network_egress.httpx.Client", _FakeClient)

    http_request(
        ToolInvocation(action="http.request", input={"method": "HEAD", "url": "https://example.com/status"}),
        _context(),
    )

    request = _FakeClient.instances[0].requests[0]
    assert _FakeClient.instances[0].kwargs["follow_redirects"] is False
    assert request["follow_redirects"] is False
    assert request["headers"]["Connection"] == "close"


def test_http_request_truncates_response_body_to_4096_chars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("socket.getaddrinfo", _public_dns)
    monkeypatch.setattr("backend.services.network_egress.httpx.Client", _FakeClient)
    _FakeClient.response_text = "x" * 4097

    result = http_request(
        ToolInvocation(action="http.request", input={"method": "GET", "url": "https://example.com/large"}),
        _context(),
    )

    assert result.output["body_text"] == "x" * 4096
    assert result.output["body_truncated"] is True


def test_calendar_create_event_is_observable_by_read() -> None:
    import uuid

    from backend.services.tools.action_registry import get_default_action_registry
    from backend.services.tools.local_calendar import reset_default_local_calendar_provider
    from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation

    reset_default_local_calendar_provider()
    registry = get_default_action_registry(rebuild=True)
    context = ActionRuntimeContext(
        tenant_id=str(uuid.uuid4()),
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        worker_id="worker",
        lease_id=str(uuid.uuid4()),
    )

    create_result = registry.invoke(
        ToolInvocation(
            action="calendar.create_event",
            input={
                "calendar_id": "primary",
                "title": "Discovery Call",
                "start": "2026-06-05T10:00:00Z",
                "end": "2026-06-05T10:30:00Z",
            },
        ),
        context,
    )
    read_result = registry.invoke(
        ToolInvocation(action="calendar.read", input={"calendar_id": "primary"}),
        context,
    )

    assert create_result.records_changed == ["evt-1"]
    assert read_result.output["count"] == 1
    assert read_result.output["events"][0]["title"] == "Discovery Call"


def test_calendar_read_honors_start_and_end_windows() -> None:
    import uuid

    from backend.services.tools.action_registry import get_default_action_registry
    from backend.services.tools.local_calendar import reset_default_local_calendar_provider
    from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation

    tenant_id = str(uuid.uuid4())
    reset_default_local_calendar_provider(
        {
            tenant_id: {
                "primary": [
                    {
                        "id": "evt-before",
                        "calendar_id": "primary",
                        "title": "Before",
                        "start": "2026-06-05T08:00:00Z",
                        "end": "2026-06-05T08:30:00Z",
                    },
                    {
                        "id": "evt-window",
                        "calendar_id": "primary",
                        "title": "In Window",
                        "start": "2026-06-05T10:00:00Z",
                        "end": "2026-06-05T10:30:00Z",
                    },
                    {
                        "id": "evt-after",
                        "calendar_id": "primary",
                        "title": "After",
                        "start": "2026-06-05T12:00:00Z",
                        "end": "2026-06-05T12:30:00Z",
                    },
                ]
            }
        }
    )
    registry = get_default_action_registry(rebuild=True)
    context = ActionRuntimeContext(
        tenant_id=tenant_id,
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        worker_id="worker",
        lease_id=str(uuid.uuid4()),
    )

    result = registry.invoke(
        ToolInvocation(
            action="calendar.read",
            input={
                "calendar_id": "primary",
                "start": "2026-06-05T09:00:00Z",
                "end": "2026-06-05T11:00:00Z",
            },
        ),
        context,
    )

    assert result.output["count"] == 1
    assert result.output["events"][0]["id"] == "evt-window"


def test_webhook_dispatch_derives_stable_event_id_from_idempotency_key(monkeypatch: pytest.MonkeyPatch) -> None:
    import uuid

    from backend.services.tools.action_registry import get_default_action_registry
    from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation
    from backend.services.webhook_dispatch import WebhookDispatchResult

    captured_event_ids: list[uuid.UUID] = []

    class Session:
        def commit(self) -> None:
            return None

        def rollback(self) -> None:
            return None

        def close(self) -> None:
            return None

    class Service:
        def __init__(self, session: Session) -> None:
            self.session = session

        def dispatch_event(self, **kwargs):
            captured_event_ids.append(kwargs["event_id"])
            return [
                WebhookDispatchResult(
                    delivery_id=uuid.uuid4(),
                    succeeded=True,
                    http_status=200,
                )
            ]

    monkeypatch.setattr("backend.services.tools.webhook_actions.WebhookDispatchService", Service)

    tenant_id = str(uuid.uuid4())
    task_id = uuid.uuid4()
    context = ActionRuntimeContext(
        tenant_id=tenant_id,
        task_id=task_id,
        mission_id=uuid.uuid4(),
        worker_id="worker",
        lease_id=str(uuid.uuid4()),
        session_factory=Session,
    )
    registry = get_default_action_registry(rebuild=True)
    invocation = ToolInvocation(
        action="webhook.dispatch",
        idempotency_key="stable-key",
        input={"event_type": "task.completed", "payload": {"ok": True}},
    )

    first = registry.invoke(invocation, context)
    second = registry.invoke(invocation, context)

    assert captured_event_ids[0] == captured_event_ids[1]
    assert first.output["event_id"] == second.output["event_id"] == str(captured_event_ids[0])


def test_calendar_read_normalizes_offset_times_before_window_filtering() -> None:
    import uuid

    from backend.services.tools.action_registry import get_default_action_registry
    from backend.services.tools.local_calendar import reset_default_local_calendar_provider
    from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation

    tenant_id = str(uuid.uuid4())
    reset_default_local_calendar_provider(
        {
            tenant_id: {
                "primary": [
                    {
                        "id": "evt-before-window",
                        "calendar_id": "primary",
                        "title": "Before window",
                        "start": "2026-06-05T10:00:00-05:00",
                        "end": "2026-06-05T10:30:00-05:00",
                    },
                    {
                        "id": "evt-in-window",
                        "calendar_id": "primary",
                        "title": "In window",
                        "start": "2026-06-05T07:30:00-05:00",
                        "end": "2026-06-05T08:30:00-05:00",
                    },
                ]
            }
        }
    )
    context = ActionRuntimeContext(
        tenant_id=tenant_id,
        task_id=uuid.uuid4(),
        mission_id=None,
        worker_id="worker",
        lease_id=str(uuid.uuid4()),
    )
    registry = get_default_action_registry(rebuild=True)

    result = registry.invoke(
        ToolInvocation(
            action="calendar.read",
            input={
                "calendar_id": "primary",
                "start": "2026-06-05T12:00:00Z",
                "end": "2026-06-05T14:00:00Z",
            },
        ),
        context,
    )

    assert [event["id"] for event in result.output["events"]] == ["evt-in-window"]


def test_http_request_allowed_hosts_cannot_bypass_destination_safety(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PRIVATE_ADDR, 443))],
    )

    with pytest.raises(ValueError, match="private DNS"):
        vet_safe_http_destination("https://example.com/path", allowed_hosts=["example.com"])


def test_http_request_network_failure_error_is_evidence_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingClient(_FakeClient):
        def request(self, method: str, url: str, **kwargs: Any) -> _FakeResponse:
            raise httpx.ConnectError("token=super-secret")

    monkeypatch.setattr("socket.getaddrinfo", _public_dns)
    monkeypatch.setattr("backend.services.network_egress.httpx.Client", FailingClient)

    with pytest.raises(ValueError) as exc_info:
        http_request(
            ToolInvocation(action="http.request", input={"method": "GET", "url": "https://example.com/secret"}),
            _context(),
        )

    assert "network request failed" in str(exc_info.value)
    assert "super-secret" not in str(exc_info.value)


def test_http_request_registry_result_and_evidence_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.services.tools.action_registry import get_default_action_registry

    monkeypatch.setattr("socket.getaddrinfo", _public_dns)
    monkeypatch.setattr("backend.services.network_egress.httpx.Client", _FakeClient)
    registry = get_default_action_registry(rebuild=True)
    context = _context()

    result = registry.invoke(
        ToolInvocation(action="http.request", input={"method": "HEAD", "url": "https://example.com/status"}),
        context,
    )

    assert result.side_effect_class.value == "external_read"
    assert result.evidence[0].tenant_id == context.tenant_id
    assert result.evidence[0].side_effect_class == result.side_effect_class
    assert result.evidence[0].provenance["network_egress_authority"].endswith("NetworkEgressAuthority")
