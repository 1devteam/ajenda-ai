from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.services.internet.open_write import (
    execute_open_write,
    reset_open_write_rate_limiter_for_tests,
)
from backend.services.network_egress import NetworkEgressResponse, VettedNetworkDestination


def setup_function() -> None:
    reset_open_write_rate_limiter_for_tests()


def test_open_write_disabled_fails_closed(monkeypatch) -> None:
    monkeypatch.setenv("AJENDA_OPEN_WRITE_ENABLED", "false")
    # bypass cached settings if present
    from backend.app import config as config_mod

    if hasattr(config_mod.get_settings, "cache_clear"):
        config_mod.get_settings.cache_clear()
    result = execute_open_write(
        tenant_id="t1",
        url="https://example.com/form",
        method="POST",
        idempotency_key="idem-key-123456",
        json_body={"a": 1},
    )
    assert result.real is False
    assert "disabled" in (result.error or "")


def test_open_write_requires_idempotency_key(monkeypatch) -> None:
    monkeypatch.setenv("AJENDA_OPEN_WRITE_ENABLED", "true")
    from backend.app import config as config_mod

    if hasattr(config_mod.get_settings, "cache_clear"):
        config_mod.get_settings.cache_clear()
    result = execute_open_write(
        tenant_id="t1",
        url="https://example.com/form",
        method="POST",
        idempotency_key="   ",
        json_body={"a": 1},
    )
    assert result.real is False
    assert "idempotency" in (result.error or "")


def test_open_write_rate_limit(monkeypatch) -> None:
    monkeypatch.setenv("AJENDA_OPEN_WRITE_ENABLED", "true")
    monkeypatch.setenv("AJENDA_OPEN_WRITE_MAX_PER_HOUR", "2")
    from backend.app import config as config_mod

    if hasattr(config_mod.get_settings, "cache_clear"):
        config_mod.get_settings.cache_clear()
    reset_open_write_rate_limiter_for_tests()

    destination = VettedNetworkDestination(
        original_url="https://example.com/form",
        connect_url="https://1.2.3.4/form",
        pinned_ip=__import__("ipaddress").ip_address("1.2.3.4"),
        sni_hostname="example.com",
        host_header="example.com",
    )
    response = NetworkEgressResponse(status_code=200, headers={}, body_text="ok", body_truncated=False)
    authority = MagicMock()
    authority.request.return_value = (destination, response)

    with patch(
        "backend.services.internet.open_write.get_default_network_egress_authority",
        return_value=authority,
    ):
        r1 = execute_open_write(
            tenant_id="t-rate",
            url="https://example.com/form",
            method="POST",
            idempotency_key="key-aaaaaaaa",
            json_body={"n": 1},
        )
        r2 = execute_open_write(
            tenant_id="t-rate",
            url="https://example.com/form",
            method="POST",
            idempotency_key="key-bbbbbbbb",
            json_body={"n": 2},
        )
        r3 = execute_open_write(
            tenant_id="t-rate",
            url="https://example.com/form",
            method="POST",
            idempotency_key="key-cccccccc",
            json_body={"n": 3},
        )
    assert r1.real is True
    assert r2.real is True
    assert r3.real is False
    assert "rate limit" in (r3.error or "")


def test_open_write_idempotency_replays_without_second_network_call(monkeypatch) -> None:
    monkeypatch.setenv("AJENDA_OPEN_WRITE_ENABLED", "true")
    from backend.app import config as config_mod

    if hasattr(config_mod.get_settings, "cache_clear"):
        config_mod.get_settings.cache_clear()
    reset_open_write_rate_limiter_for_tests()

    destination = VettedNetworkDestination(
        original_url="https://example.com/form",
        connect_url="https://1.2.3.4/form",
        pinned_ip=__import__("ipaddress").ip_address("1.2.3.4"),
        sni_hostname="example.com",
        host_header="example.com",
    )
    response = NetworkEgressResponse(status_code=201, headers={}, body_text="created", body_truncated=False)
    authority = MagicMock()
    authority.request.return_value = (destination, response)

    with patch(
        "backend.services.internet.open_write.get_default_network_egress_authority",
        return_value=authority,
    ):
        first = execute_open_write(
            tenant_id="t-idem",
            url="https://example.com/form",
            method="POST",
            idempotency_key="stable-idem-key-01",
            json_body={"n": 1},
        )
        second = execute_open_write(
            tenant_id="t-idem",
            url="https://example.com/form",
            method="POST",
            idempotency_key="stable-idem-key-01",
            json_body={"n": 1},
        )
    assert first.real is True
    assert first.idempotency_decision == "newly_claimed"
    assert second.real is True
    assert second.idempotency_decision == "replayed"
    assert second.status_code == 201
    assert authority.request.call_count == 1


def test_open_write_rejects_credentialed_url(monkeypatch) -> None:
    monkeypatch.setenv("AJENDA_OPEN_WRITE_ENABLED", "true")
    from backend.app import config as config_mod

    if hasattr(config_mod.get_settings, "cache_clear"):
        config_mod.get_settings.cache_clear()
    result = execute_open_write(
        tenant_id="t1",
        url="https://user:pass@example.com/form",
        method="POST",
        idempotency_key="idem-key-123456",
        json_body={"a": 1},
    )
    assert result.real is False
    assert "userinfo" in (result.error or "")
