from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.services.internet.browser_session import run_browser_session
from backend.services.internet.modes import InternetAccessMode
from backend.services.network_egress import NetworkEgressError


def test_browser_session_disabled_fails_closed(monkeypatch) -> None:
    monkeypatch.setenv("AJENDA_BROWSER_SESSION_ENABLED", "false")
    from backend.app import config as config_mod

    if hasattr(config_mod.get_settings, "cache_clear"):
        config_mod.get_settings.cache_clear()
    snapshot = run_browser_session(url_or_domain="https://example.com")
    assert snapshot.real is False
    assert snapshot.access_mode == InternetAccessMode.BROWSER_SESSION
    assert "disabled" in (snapshot.error or "")


def test_browser_session_vets_url_before_playwright(monkeypatch) -> None:
    monkeypatch.setenv("AJENDA_BROWSER_SESSION_ENABLED", "true")
    from backend.app import config as config_mod

    if hasattr(config_mod.get_settings, "cache_clear"):
        config_mod.get_settings.cache_clear()

    authority = MagicMock()
    authority.vet_https_url.side_effect = NetworkEgressError(
        "web.browser_session blocked private DNS resolution"
    )
    with patch(
        "backend.services.internet.browser_session.get_default_network_egress_authority",
        return_value=authority,
    ):
        snapshot = run_browser_session(url_or_domain="https://localhost/")
    assert snapshot.real is False
    assert "blocked" in (snapshot.error or "")
    # Playwright must not be imported/started if vet fails — we only assert fail-closed.
    authority.vet_https_url.assert_called()
