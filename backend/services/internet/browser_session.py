"""Ephemeral headless browser session (Playwright prototype).

Security rules:
- URL must pass NetworkEgressAuthority.vet_https_url before navigation.
- One browser + one context per call; always destroyed before return.
- Never reuse browser instances across tenants or leases.
- Disabled unless AJENDA_BROWSER_SESSION_ENABLED=true.
"""

from __future__ import annotations

from typing import Any, Literal

from backend.services.internet.contracts import PageSnapshot
from backend.services.internet.modes import InternetAccessMode
from backend.services.internet.page_read import normalize_page_url
from backend.services.network_egress import NetworkEgressError, get_default_network_egress_authority

WaitUntil = Literal["domcontentloaded", "load", "networkidle"]
DEFAULT_TEXT_LIMIT = 4_000


def browser_session_enabled() -> bool:
    try:
        from backend.app.config import get_settings

        return bool(get_settings().browser_session_enabled)
    except Exception:
        import os

        return (os.environ.get("AJENDA_BROWSER_SESSION_ENABLED") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }


def run_browser_session(
    *,
    url_or_domain: str,
    timeout_seconds: float = 15.0,
    wait_until: WaitUntil = "domcontentloaded",
    extract_text: bool = True,
) -> PageSnapshot:
    """Navigate once, extract title/text, destroy browser. Fail closed when disabled."""

    if not browser_session_enabled():
        return PageSnapshot(
            url=url_or_domain,
            real=False,
            error="browser_session disabled (set AJENDA_BROWSER_SESSION_ENABLED=true)",
            access_mode=InternetAccessMode.BROWSER_SESSION,
            browser_ready=False,
        )

    try:
        page_url = normalize_page_url(url_or_domain)
    except ValueError as exc:
        return PageSnapshot(
            url=url_or_domain,
            real=False,
            error=str(exc),
            access_mode=InternetAccessMode.BROWSER_SESSION,
            browser_ready=False,
        )

    # Fail closed on private/internal destinations before Chromium starts.
    try:
        get_default_network_egress_authority().vet_https_url(
            page_url,
            action_name="web.browser_session",
        )
    except NetworkEgressError as exc:
        return PageSnapshot(
            url=page_url,
            real=False,
            error=str(exc),
            access_mode=InternetAccessMode.BROWSER_SESSION,
            browser_ready=False,
        )

    try:
        from playwright.sync_api import sync_playwright  # type: ignore[import-untyped]
    except ImportError as exc:
        return PageSnapshot(
            url=page_url,
            real=False,
            error=f"playwright not installed: {exc}",
            access_mode=InternetAccessMode.BROWSER_SESSION,
            browser_ready=False,
        )

    timeout_ms = int(min(max(timeout_seconds, 1.0), 60.0) * 1000)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                # Isolated context per invocation — never shared across tenants.
                context = browser.new_context(
                    user_agent="AjendaInternet/1.0 (+browser_session)",
                    java_script_enabled=True,
                    ignore_https_errors=False,
                )
                try:
                    page = context.new_page()
                    response = page.goto(page_url, wait_until=wait_until, timeout=timeout_ms)
                    title = (page.title() or "").strip()[:240] or None
                    text_preview = None
                    if extract_text:
                        try:
                            body_text = page.inner_text("body", timeout=min(timeout_ms, 10_000))
                            text_preview = " ".join((body_text or "").split())[:DEFAULT_TEXT_LIMIT] or None
                        except Exception:
                            text_preview = None
                    status_code = response.status if response is not None else None
                    return PageSnapshot(
                        url=page_url,
                        real=True,
                        status_code=status_code,
                        title=title,
                        text_preview=text_preview,
                        body_preview=(text_preview or "")[:500] or None,
                        body_truncated=bool(text_preview and len(text_preview) >= DEFAULT_TEXT_LIMIT),
                        content_type=None,
                        access_mode=InternetAccessMode.BROWSER_SESSION,
                        browser_ready=True,
                        extraction={
                            "engine": "playwright_chromium",
                            "wait_until": wait_until,
                            "ephemeral_context": True,
                        },
                    )
                finally:
                    context.close()
            finally:
                browser.close()
    except Exception as exc:
        return PageSnapshot(
            url=page_url,
            real=False,
            error=str(exc),
            access_mode=InternetAccessMode.BROWSER_SESSION,
            browser_ready=False,
        )


def browser_session_as_dict(snapshot: PageSnapshot) -> dict[str, Any]:
    payload = snapshot.as_dict()
    payload["ephemeral"] = True
    payload["tenant_isolation"] = "single_use_context"
    return payload
