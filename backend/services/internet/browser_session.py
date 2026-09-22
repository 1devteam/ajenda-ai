"""Ephemeral headless browser session (Playwright prototype).

Security rules:
- URL must pass NetworkEgressAuthority.vet_https_url before navigation.
- Every request (redirects, subresources, frames) is re-vetted via route intercept.
- One browser + one context per call; always destroyed before return.
- Never reuse browser instances across tenants or leases.
- Disabled unless AJENDA_BROWSER_SESSION_ENABLED=true.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlparse

from backend.services.internet.contracts import PageSnapshot
from backend.services.internet.modes import InternetAccessMode
from backend.services.internet.page_read import normalize_page_url
from backend.services.internet.url_safety import reject_credentialed_url
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


def assert_browser_runtime_ready() -> None:
    """Fail worker startup when browser execution is enabled but unavailable."""

    if not browser_session_enabled():
        return
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            browser.close()
    except Exception as exc:
        raise RuntimeError("AJENDA_BROWSER_SESSION_ENABLED requires a working Playwright Chromium runtime") from exc


def _vet_browser_destination(url: str) -> None:
    if not url.startswith("https://"):
        raise NetworkEgressError("web.browser_session only allows https URLs")
    reject_credentialed_url(url, action_name="web.browser_session")
    get_default_network_egress_authority().vet_https_url(url, action_name="web.browser_session")


def _allowed_hosts(page_url: str, allowed_origins: Sequence[str]) -> tuple[str, ...]:
    """Resolve the contract's origin allow-list to exact HTTPS host names."""

    origins = tuple(allowed_origins) or (page_url,)
    hosts: list[str] = []
    for origin in origins:
        parsed = urlparse(origin)
        if parsed.scheme != "https" or not parsed.hostname:
            raise NetworkEgressError("web.browser_session allowed_origins must be HTTPS URLs")
        host = parsed.hostname.lower().rstrip(".")
        if host not in hosts:
            hosts.append(host)
    return tuple(hosts)


def _step_text(page: Any, selector: str, limit: int, timeout_ms: int) -> str:
    value = page.locator(selector).inner_text(timeout=min(timeout_ms, 10_000))
    return " ".join((value or "").split())[:limit]


def run_browser_session(
    *,
    url_or_domain: str,
    timeout_seconds: float = 15.0,
    wait_until: WaitUntil = "domcontentloaded",
    extract_text: bool = True,
    allowed_origins: Sequence[str] = (),
    commands: Sequence[Mapping[str, Any]] = (),
    observation_requirements: Sequence[Mapping[str, Any]] = (),
) -> PageSnapshot:
    """Run a bounded read-only browser contract and destroy the context."""

    if not browser_session_enabled():
        return PageSnapshot(
            url=url_or_domain,
            real=False,
            error="browser_session disabled (set AJENDA_BROWSER_SESSION_ENABLED=true)",
            access_mode=InternetAccessMode.BROWSER_SESSION,
            browser_ready=False,
        )

    try:
        reject_credentialed_url(url_or_domain, action_name="web.browser_session")
        page_url = normalize_page_url(url_or_domain)
        allowed_hosts = _allowed_hosts(page_url, allowed_origins)
        if (urlparse(page_url).hostname or "").lower().rstrip(".") not in allowed_hosts:
            raise NetworkEgressError("web.browser_session start URL is outside allowed_origins")
        _vet_browser_destination(page_url)
    except (ValueError, NetworkEgressError) as exc:
        return PageSnapshot(
            url=url_or_domain,
            real=False,
            error=str(exc),
            access_mode=InternetAccessMode.BROWSER_SESSION,
            browser_ready=False,
        )

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        return PageSnapshot(
            url=page_url,
            real=False,
            error=f"playwright not installed: {exc}",
            access_mode=InternetAccessMode.BROWSER_SESSION,
            browser_ready=False,
        )

    timeout_ms = int(min(max(timeout_seconds, 1.0), 60.0) * 1000)
    blocked: list[str] = []
    steps: list[dict[str, Any]] = []

    def _route_handler(route: Any) -> None:
        request_url = str(getattr(route.request, "url", "") or "")
        try:
            reject_credentialed_url(request_url, action_name="web.browser_session")
            get_default_network_egress_authority().vet_https_url(
                request_url,
                allowed_hosts=list(allowed_hosts),
                action_name="web.browser_session",
            )
        except (ValueError, NetworkEgressError) as exc:
            blocked.append(f"{request_url[:160]} ({exc})")
            route.abort()
            return
        route.continue_()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    user_agent="AjendaInternet/1.0 (+browser_session)",
                    java_script_enabled=True,
                    ignore_https_errors=False,
                )
                try:
                    # Intercept redirects, frames, and subresources — not only the first hop.
                    context.route("**/*", _route_handler)
                    page = context.new_page()
                    response = page.goto(page_url, wait_until=wait_until, timeout=timeout_ms)
                    final_url = (page.url or page_url).strip() or page_url
                    title = (page.title() or "").strip()[:240] or None
                    text_preview = None
                    if extract_text:
                        try:
                            body_text = page.inner_text("body", timeout=min(timeout_ms, 10_000))
                            text_preview = " ".join((body_text or "").split())[:DEFAULT_TEXT_LIMIT] or None
                        except Exception:
                            text_preview = None
                    status_code = response.status if response is not None else None
                    steps.append(
                        {
                            "index": 0,
                            "action": "navigate",
                            "url": page_url,
                            "final_url": final_url,
                            "status_code": status_code,
                        }
                    )
                    for index, command in enumerate(commands, start=1):
                        action = str(command.get("action") or "").strip()
                        if action == "navigate":
                            target = str(command.get("url") or "").strip()
                            if not target:
                                raise ValueError("navigate step requires url")
                            normalized_target = normalize_page_url(target)
                            if (urlparse(normalized_target).hostname or "").lower().rstrip(".") not in allowed_hosts:
                                raise NetworkEgressError("navigate step is outside allowed_origins")
                            _vet_browser_destination(normalized_target)
                            response = page.goto(
                                normalized_target,
                                wait_until=wait_until,
                                timeout=timeout_ms,
                            )
                            final_url = (page.url or normalized_target).strip() or normalized_target
                            steps.append(
                                {
                                    "index": index,
                                    "action": action,
                                    "url": normalized_target,
                                    "final_url": final_url,
                                    "status_code": response.status if response is not None else None,
                                }
                            )
                        elif action == "observe":
                            observed_title = (page.title() or "").strip()[:240] or None
                            observed_text = _step_text(page, "body", 4_000, timeout_ms)
                            text_preview = observed_text or text_preview
                            title = observed_title or title
                            steps.append(
                                {
                                    "index": index,
                                    "action": action,
                                    "url": page.url,
                                    "title": observed_title,
                                    "text_preview": observed_text,
                                }
                            )
                        elif action == "extract":
                            selector = str(command.get("selector") or "body").strip()
                            extracted = _step_text(page, selector, int(command.get("text_limit") or 4_000), timeout_ms)
                            steps.append(
                                {
                                    "index": index,
                                    "action": action,
                                    "url": page.url,
                                    "selector": selector,
                                    "text": extracted,
                                }
                            )
                            text_preview = extracted or text_preview
                        else:
                            raise ValueError(f"unsupported browser step: {action or '<missing action>'}")
                    requirement_results: list[dict[str, Any]] = []
                    for requirement in observation_requirements:
                        kind = str(requirement.get("kind") or "").strip()
                        minimum = int(requirement.get("min_length") or 1)
                        if kind == "title":
                            observed_value = title or ""
                        elif kind == "body":
                            observed_value = text_preview or ""
                        elif kind == "selector_text":
                            selector = str(requirement.get("selector") or "").strip()
                            observed_value = _step_text(page, selector, 4_000, timeout_ms) if selector else ""
                        else:
                            raise ValueError(f"unsupported observation requirement: {kind or '<missing kind>'}")
                        requirement_results.append(
                            {
                                "kind": kind,
                                "selector": requirement.get("selector"),
                                "observed": bool(observed_value),
                                "satisfied": len(observed_value) >= minimum,
                                "value": observed_value[:4_000],
                            }
                        )
                    observation_satisfied = all(item["satisfied"] for item in requirement_results)
                    return PageSnapshot(
                        url=final_url,
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
                            "request_vetting": "network_egress_per_request",
                            "requested_url": page_url,
                            "final_url": final_url,
                            "blocked_request_count": len(blocked),
                            "blocked_samples": blocked[:5],
                            "allowed_hosts": list(allowed_hosts),
                            "steps": steps,
                            "observation_requirements": requirement_results,
                            "observation_satisfied": observation_satisfied,
                            "observation_timestamp": datetime.now(UTC).isoformat(),
                            # Chromium still resolves hosts after vet; DNS pin of every
                            # subresource is a follow-up (route.fulfill via egress).
                            "dns_pin": "vet_only",
                        },
                    )
                finally:
                    context.close()
            finally:
                browser.close()
    except PlaywrightError as exc:
        return PageSnapshot(
            url=page_url,
            real=False,
            error=str(exc),
            access_mode=InternetAccessMode.BROWSER_SESSION,
            browser_ready=False,
            extraction={"blocked_request_count": len(blocked), "blocked_samples": blocked[:5]},
        )
    except Exception as exc:
        return PageSnapshot(
            url=page_url,
            real=False,
            error=str(exc),
            access_mode=InternetAccessMode.BROWSER_SESSION,
            browser_ready=False,
            extraction={"blocked_request_count": len(blocked), "blocked_samples": blocked[:5]},
        )


def browser_session_as_dict(snapshot: PageSnapshot) -> dict[str, Any]:
    payload = snapshot.as_dict()
    payload["ephemeral"] = True
    payload["tenant_isolation"] = "single_use_context"
    return payload
