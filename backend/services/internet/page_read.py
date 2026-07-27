"""Public page read — single HTTPS GET + bounded HTML text extraction.

This is intentionally not a browser: no JS execution, no multi-step navigation.
BROWSER_SESSION is the reserved mode for headless multi-step work later.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

from backend.services.internet.contracts import PageSnapshot
from backend.services.internet.modes import InternetAccessMode
from backend.services.network_egress import (
    DEFAULT_RESPONSE_TEXT_LIMIT,
    get_default_network_egress_authority,
)

# Larger than default snippet path so title/meta/body extraction has enough signal.
PAGE_READ_RESPONSE_LIMIT = 65_536
DEFAULT_TEXT_PREVIEW_CHARS = 2_000
DEFAULT_BODY_PREVIEW_CHARS = 500
_AJENDA_PAGE_UA = "AjendaInternet/1.0 (+page_read)"


class _HtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.meta_description: str | None = None
        self._in_title = False
        self._skip_depth = 0
        self._skip_tags = {"script", "style", "noscript", "svg", "template"}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lower = tag.lower()
        if lower in self._skip_tags:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if lower == "title":
            self._in_title = True
        if lower == "meta":
            attr_map = {k.lower(): (v or "") for k, v in attrs if k}
            name = attr_map.get("name", "").lower() or attr_map.get("property", "").lower()
            if name in {"description", "og:description"} and attr_map.get("content"):
                self.meta_description = attr_map["content"].strip()[:500]

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if lower in self._skip_tags and self._skip_depth:
            self._skip_depth -= 1
            return
        if lower == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        else:
            self.text_parts.append(text)


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def extract_html_snapshot(html: str) -> dict[str, Any]:
    parser = _HtmlTextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        # Malformed HTML must not fail the action; fall back to raw body preview.
        return {
            "title": None,
            "meta_description": None,
            "text_preview": _normalize_whitespace(re.sub(r"<[^>]+>", " ", html))[:DEFAULT_TEXT_PREVIEW_CHARS],
            "parser": "fallback_strip_tags",
        }
    title = _normalize_whitespace(" ".join(parser.title_parts))[:240] or None
    text = _normalize_whitespace(" ".join(parser.text_parts))
    if parser.meta_description and parser.meta_description not in text:
        text = f"{parser.meta_description} {text}".strip()
    return {
        "title": title,
        "meta_description": parser.meta_description,
        "text_preview": text[:DEFAULT_TEXT_PREVIEW_CHARS],
        "parser": "html.parser",
    }


def normalize_page_url(url_or_domain: str) -> str:
    raw = url_or_domain.strip()
    if not raw:
        raise ValueError("page url is required")
    if "://" not in raw:
        host = raw.lstrip(".").split("/")[0]
        return f"https://{host}/"
    parsed = urlparse(raw)
    if parsed.scheme.lower() != "https":
        raise ValueError("page_read only allows https URLs")
    if not parsed.netloc:
        raise ValueError("page_read URL must include a hostname")
    return raw


def _host_allowlist_for_url(url: str) -> list[str]:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    return [host] if host else []


def fetch_public_page(
    *,
    url_or_domain: str,
    timeout_seconds: float = 8.0,
    action_name: str = "web.page_read",
    response_text_limit: int = PAGE_READ_RESPONSE_LIMIT,
) -> PageSnapshot:
    """Single-shot public page GET via NetworkEgressAuthority + HTML extraction."""

    try:
        page_url = normalize_page_url(url_or_domain)
    except ValueError as exc:
        return PageSnapshot(url=url_or_domain, real=False, error=str(exc))

    allowed_hosts = _host_allowlist_for_url(page_url)
    try:
        _dest, response = get_default_network_egress_authority().request(
            method="GET",
            url=page_url,
            headers={"User-Agent": _AJENDA_PAGE_UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
            allowed_hosts=allowed_hosts or None,
            action_name=action_name,
            timeout_seconds=min(timeout_seconds, 15.0),
            response_text_limit=response_text_limit,
        )
        content_type = None
        for key, value in response.headers.items():
            if key.lower() == "content-type":
                content_type = value
                break
        body = response.body_text or ""
        extraction = (
            extract_html_snapshot(body)
            if body
            else {
                "title": None,
                "meta_description": None,
                "text_preview": "",
                "parser": "empty",
            }
        )
        return PageSnapshot(
            url=page_url,
            real=True,
            status_code=response.status_code,
            title=extraction.get("title") if isinstance(extraction.get("title"), str) else None,
            text_preview=str(extraction.get("text_preview") or "")[:DEFAULT_TEXT_PREVIEW_CHARS] or None,
            body_preview=body[:DEFAULT_BODY_PREVIEW_CHARS] if body else None,
            body_truncated=response.body_truncated,
            content_type=content_type,
            extraction={
                "parser": extraction.get("parser"),
                "meta_description": extraction.get("meta_description"),
                "response_text_limit": response_text_limit,
                "default_snippet_limit": DEFAULT_RESPONSE_TEXT_LIMIT,
            },
            # Explicit: this path is not a browser; reserved mode stays closed.
            browser_ready=False,
            access_mode=InternetAccessMode.PAGE_READ,
        )
    except Exception as exc:
        return PageSnapshot(
            url=page_url,
            real=False,
            error=str(exc),
            access_mode=InternetAccessMode.PAGE_READ,
            browser_ready=False,
        )
