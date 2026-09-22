from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.services.internet.browser_session import assert_browser_runtime_ready, run_browser_session
from backend.services.internet.modes import InternetAccessMode
from backend.services.network_egress import NetworkEgressError


class _FakeResponse:
    status = 200


class _FakePage:
    def __init__(self) -> None:
        self.url = "https://example.com/"
        self.clicked: list[str] = []

    def goto(self, url: str, **_kwargs):
        self.url = url
        return _FakeResponse()

    def title(self) -> str:
        return "Example"

    def inner_text(self, _selector: str = "body", **_kwargs) -> str:
        return "Example body"

    def locator(self, _selector: str):
        return self

    def click(self, **_kwargs) -> None:
        self.clicked.append("clicked")

    def wait_for_load_state(self, _state: str, **_kwargs) -> None:
        return None


class _FakeContext:
    def route(self, _pattern: str, _handler) -> None:
        return None

    def new_page(self) -> _FakePage:
        return _FakePage()

    def close(self) -> None:
        return None


class _FakeBrowser:
    def new_context(self, **_kwargs) -> _FakeContext:
        return _FakeContext()

    def close(self) -> None:
        return None


class _FakeChromium:
    def launch(self, **_kwargs) -> _FakeBrowser:
        return _FakeBrowser()


class _FakePlaywright:
    chromium = _FakeChromium()

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None


def test_browser_session_disabled_fails_closed(monkeypatch) -> None:
    monkeypatch.setenv("AJENDA_BROWSER_SESSION_ENABLED", "false")
    from backend.app import config as config_mod

    if hasattr(config_mod.get_settings, "cache_clear"):
        config_mod.get_settings.cache_clear()
    snapshot = run_browser_session(url_or_domain="https://example.com")
    assert snapshot.real is False
    assert snapshot.access_mode == InternetAccessMode.BROWSER_SESSION
    assert "disabled" in (snapshot.error or "")


def test_browser_runtime_readiness_is_noop_when_disabled(monkeypatch) -> None:
    monkeypatch.setenv("AJENDA_BROWSER_SESSION_ENABLED", "false")
    assert_browser_runtime_ready()


def test_browser_runtime_readiness_fails_closed_when_launch_fails(monkeypatch) -> None:
    monkeypatch.setenv("AJENDA_BROWSER_SESSION_ENABLED", "true")
    from backend.app import config as config_mod

    if hasattr(config_mod.get_settings, "cache_clear"):
        config_mod.get_settings.cache_clear()

    with patch("playwright.sync_api.sync_playwright", side_effect=RuntimeError("browser missing")):
        try:
            assert_browser_runtime_ready()
        except RuntimeError as exc:
            assert "working Playwright Chromium runtime" in str(exc)
        else:
            raise AssertionError("browser readiness must fail when Chromium cannot launch")


def test_browser_session_vets_url_before_playwright(monkeypatch) -> None:
    monkeypatch.setenv("AJENDA_BROWSER_SESSION_ENABLED", "true")
    from backend.app import config as config_mod

    if hasattr(config_mod.get_settings, "cache_clear"):
        config_mod.get_settings.cache_clear()

    authority = MagicMock()
    authority.vet_https_url.side_effect = NetworkEgressError("web.browser_session blocked private DNS resolution")
    with patch(
        "backend.services.internet.browser_session.get_default_network_egress_authority",
        return_value=authority,
    ):
        snapshot = run_browser_session(url_or_domain="https://localhost/")
    assert snapshot.real is False
    assert "blocked" in (snapshot.error or "")
    # Playwright must not be imported/started if vet fails — we only assert fail-closed.
    authority.vet_https_url.assert_called()


def test_browser_session_runs_bounded_read_only_steps(monkeypatch) -> None:
    monkeypatch.setenv("AJENDA_BROWSER_SESSION_ENABLED", "true")
    from backend.app import config as config_mod

    if hasattr(config_mod.get_settings, "cache_clear"):
        config_mod.get_settings.cache_clear()

    authority = MagicMock()
    with (
        patch(
            "backend.services.internet.browser_session.get_default_network_egress_authority",
            return_value=authority,
        ),
        patch("playwright.sync_api.sync_playwright", return_value=_FakePlaywright()),
    ):
        snapshot = run_browser_session(
            url_or_domain="https://example.com",
            allowed_origins=("https://example.com",),
            commands=(
                {"action": "observe"},
                {"action": "extract", "selector": "body", "text_limit": 200},
                {"action": "click", "selector": "text=More information"},
            ),
        )

    assert snapshot.real is True
    assert snapshot.browser_ready is True
    assert snapshot.extraction["allowed_hosts"] == ["example.com"]
    assert [step["action"] for step in snapshot.extraction["steps"]] == [
        "navigate",
        "observe",
        "extract",
        "click",
    ]
