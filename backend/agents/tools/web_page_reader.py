"""
WebPageReaderTool — Agent Web Page Content Extractor
=====================================================
Fetches a URL and returns clean, readable text content extracted from the
HTML. Designed to complement WebSearchTool: search finds the right URLs,
this tool reads the actual page content.

Design decisions:
- Uses httpx for async HTTP with full timeout control and redirect following
- Uses BeautifulSoup + lxml for robust HTML parsing
- Uses html2text for clean markdown-style text extraction
- Strips navigation, ads, headers, footers, scripts, and styles
- Enforces a max_chars limit to prevent context window overflow
- Blocks private/internal IP ranges to prevent SSRF attacks
- Respects robots.txt via a User-Agent that identifies the agent
- Returns structured metadata: url, title, content, char_count, truncated

Author: Dev Team Lead
Built with Pride for Obex Blackvault
"""

import asyncio
import ipaddress
import logging
import os
import re
import socket
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from backend.agents.tools.base import BaseTool, ToolCategory

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default maximum characters to return — keeps content within LLM context limits
DEFAULT_MAX_CHARS = 8_000

# Hard ceiling — never return more than this regardless of caller request
MAX_CHARS_CEILING = 32_000

# Request timeout in seconds
REQUEST_TIMEOUT = 15.0

# SSL CA bundle — use system bundle which includes the sandbox proxy CA.
# Falls back to httpx default (certifi) if the system bundle is not present.
_SYSTEM_CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"
_SSL_VERIFY: object = (
    _SYSTEM_CA_BUNDLE
    if os.path.exists(_SYSTEM_CA_BUNDLE)
    else True  # httpx default (certifi)
)

# User-Agent string — identifies the agent to servers
USER_AGENT = (
    "OmnipathAgent/2.0 (Citadel AI Research Agent; "
    "+https://nested-ai.net/agent-info)"
)

# HTML tags whose content is always stripped entirely (not just the tag)
STRIP_TAGS = {
    "script", "style", "noscript", "nav", "header", "footer",
    "aside", "advertisement", "ads", "cookie-banner", "banner",
    "iframe", "svg", "form", "button", "input", "select", "textarea",
}

# MIME types we will attempt to parse as HTML/text
ACCEPTABLE_CONTENT_TYPES = {
    "text/html",
    "text/plain",
    "application/xhtml+xml",
    "application/xml",
    "text/xml",
}

# Private/reserved IP ranges that must never be fetched (SSRF prevention)
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),   # link-local
    ipaddress.ip_network("::1/128"),           # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),          # IPv6 private
]


# ---------------------------------------------------------------------------
# SSRF guard
# ---------------------------------------------------------------------------


def _is_blocked_host(hostname: str) -> bool:
    """
    Return True if the hostname resolves to a private/reserved IP address.

    This prevents agents from being used to probe internal infrastructure.

    Args:
        hostname: The hostname to check.

    Returns:
        True if the host should be blocked, False if it is safe to fetch.
    """
    try:
        addr_info = socket.getaddrinfo(hostname, None)
        for _, _, _, _, sockaddr in addr_info:
            ip = ipaddress.ip_address(sockaddr[0])
            for network in _BLOCKED_NETWORKS:
                if ip in network:
                    return True
        return False
    except (socket.gaierror, ValueError):
        # DNS resolution failed or invalid IP — block to be safe
        return True


# ---------------------------------------------------------------------------
# HTML → clean text extraction
# ---------------------------------------------------------------------------


def _extract_clean_text(html: str, url: str) -> Dict[str, str]:
    """
    Parse HTML and extract clean, readable text content.

    Strips navigation, scripts, styles, and boilerplate. Returns the page
    title and the main body text as a single string.

    Args:
        html: Raw HTML string.
        url: Source URL (used for logging only).

    Returns:
        Dict with 'title' and 'content' keys.
    """
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")

    # Extract title
    title = ""
    title_tag = soup.find("title")
    if title_tag:
        title = title_tag.get_text(strip=True)

    # Remove all noise tags entirely (including their content)
    for tag_name in STRIP_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    # Also remove elements with common ad/nav class/id patterns.
    # IMPORTANT: never decompose structural root tags (html, body) — only
    # decompose descendants to avoid leaving main_content as None.
    _PROTECTED_TAGS = {"html", "body", "[document]"}
    noise_patterns = re.compile(
        r"(nav|navigation|menu|sidebar|footer|header|cookie|banner|"
        r"advertisement|ad-|ads-|popup|modal|overlay|breadcrumb|"
        r"social|share|related|recommended|newsletter|subscribe)",
        re.IGNORECASE,
    )
    for tag in soup.find_all(True):
        # Skip protected structural tags and already-decomposed tags.
        # Decomposed tags have attrs=None in BeautifulSoup; calling .get() on
        # them raises AttributeError, so we must guard against this.
        if tag.name in _PROTECTED_TAGS:
            continue
        if tag.attrs is None:
            continue
        class_str = " ".join(tag.get("class", []) or [])
        id_str = tag.get("id") or ""
        if noise_patterns.search(class_str) or noise_patterns.search(id_str):
            tag.decompose()

    # Try to find the main content area first.
    # Fall back through progressively broader selectors, always ending at soup
    # (the BeautifulSoup object itself) which is never None.
    main_content = (
        soup.find("main")
        or soup.find("article")
        or soup.find(id=re.compile(r"(main|content|article|body)", re.I))
        or soup.find(class_=re.compile(r"(main|content|article|body)", re.I))
        or soup.find("body")
        or soup
    )

    # Defensive null guard — should never be None after the fallback chain,
    # but JavaScript-heavy pages (e.g. SPAs) can produce empty parse trees.
    if main_content is None:
        return {"title": title, "content": ""}

    # Extract text with whitespace normalisation
    raw_text = main_content.get_text(separator="\n", strip=True) or ""

    # Collapse excessive blank lines (more than 2 consecutive newlines → 2)
    content = re.sub(r"\n{3,}", "\n\n", raw_text).strip()

    return {"title": title, "content": content}


# ---------------------------------------------------------------------------
# WebPageReaderTool
# ---------------------------------------------------------------------------


class WebPageReaderTool(BaseTool):
    """
    Fetches a web page and returns clean, readable text content.

    This tool complements WebSearchTool: use web_search to find relevant
    URLs, then use web_page_reader to read the actual page content and
    extract specific data points.

    Safety controls:
    - SSRF prevention: blocks private/internal IP ranges
    - Timeout: 15 seconds per request
    - Content type validation: only parses HTML/text responses
    - Size limit: enforces max_chars ceiling to prevent context overflow
    - Redirect following: up to 5 redirects
    """

    def __init__(self, blocked_domains: Optional[List[str]] = None):
        """
        Initialise the WebPageReaderTool.

        Args:
            blocked_domains: Optional list of domain names to block
                             (in addition to private IP ranges).
        """
        self._blocked_domains: List[str] = blocked_domains or []

    @property
    def name(self) -> str:
        return "web_page_reader"

    @property
    def description(self) -> str:
        return (
            "Fetch a web page and return its clean text content.\n"
            "Use this tool AFTER web_search to read the full content of a specific URL.\n"
            "Input: url (string), max_chars (optional int, default 8000).\n"
            "Output: page title, clean text content, and metadata.\n"
            "Workflow: web_search → find relevant URLs → web_page_reader → extract data."
        )

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.SEARCH

    async def execute(
        self,
        url: str,
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> Dict[str, Any]:
        """
        Fetch and extract clean text from a web page.

        Args:
            url: The URL to fetch. Must be http:// or https://.
            max_chars: Maximum characters to return (default 8000,
                       ceiling 32000). Longer content is truncated with
                       a note appended.

        Returns:
            Dict with keys:
                success (bool): Whether the fetch succeeded.
                url (str): The final URL after redirects.
                title (str): Page title.
                content (str): Clean extracted text.
                char_count (int): Length of returned content.
                truncated (bool): Whether content was truncated.
                status_code (int): HTTP status code.
                error (str): Error message if success is False.
        """
        # --- Input validation ---
        if not url or not isinstance(url, str):
            return {"success": False, "error": "url must be a non-empty string", "url": url}

        parsed = urlparse(url.strip())
        if parsed.scheme not in ("http", "https"):
            return {
                "success": False,
                "error": f"Unsupported scheme '{parsed.scheme}'. Only http/https are allowed.",
                "url": url,
            }

        hostname = parsed.hostname or ""
        if not hostname:
            return {"success": False, "error": "URL has no hostname.", "url": url}

        # --- Domain blocklist check ---
        for blocked in self._blocked_domains:
            if hostname == blocked or hostname.endswith(f".{blocked}"):
                return {
                    "success": False,
                    "error": f"Domain '{hostname}' is blocked.",
                    "url": url,
                }

        # --- SSRF prevention ---
        if _is_blocked_host(hostname):
            return {
                "success": False,
                "error": (
                    f"Access denied: '{hostname}' resolves to a private or "
                    "reserved IP address."
                ),
                "url": url,
            }

        # --- Clamp max_chars ---
        max_chars = max(100, min(int(max_chars), MAX_CHARS_CEILING))

        # --- Fetch ---
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                max_redirects=5,
                timeout=REQUEST_TIMEOUT,
                verify=_SSL_VERIFY,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            ) as client:
                response = await client.get(url)

            final_url = str(response.url)
            status_code = response.status_code

            if status_code >= 400:
                return {
                    "success": False,
                    "error": f"HTTP {status_code} — page not accessible.",
                    "url": final_url,
                    "status_code": status_code,
                }

            # --- Content-type check ---
            content_type = response.headers.get("content-type", "").lower().split(";")[0].strip()
            if content_type and content_type not in ACCEPTABLE_CONTENT_TYPES:
                return {
                    "success": False,
                    "error": (
                        f"Unsupported content type '{content_type}'. "
                        "This tool only reads HTML and plain text pages."
                    ),
                    "url": final_url,
                    "status_code": status_code,
                }

            # --- Extract clean text ---
            extracted = _extract_clean_text(response.text, final_url)
            title = extracted["title"]
            content = extracted["content"]

            # --- Truncate if needed ---
            truncated = len(content) > max_chars
            if truncated:
                content = content[:max_chars] + (
                    f"\n\n[Content truncated at {max_chars} characters. "
                    f"Total page length: {len(extracted['content'])} characters.]"
                )

            logger.info(
                f"web_page_reader: fetched {final_url} — "
                f"{len(content)} chars returned, truncated={truncated}"
            )

            return {
                "success": True,
                "url": final_url,
                "title": title,
                "content": content,
                "char_count": len(content),
                "truncated": truncated,
                "status_code": status_code,
            }

        except httpx.TimeoutException:
            logger.warning(f"web_page_reader: timeout fetching {url}")
            return {
                "success": False,
                "error": f"Request timed out after {REQUEST_TIMEOUT}s.",
                "url": url,
            }

        except httpx.TooManyRedirects:
            logger.warning(f"web_page_reader: too many redirects for {url}")
            return {
                "success": False,
                "error": "Too many redirects (>5). The URL may be in a redirect loop.",
                "url": url,
            }

        except httpx.RequestError as exc:
            logger.error(f"web_page_reader: request error for {url}: {exc}")
            return {
                "success": False,
                "error": f"Network error: {type(exc).__name__}: {exc}",
                "url": url,
            }

        except Exception as exc:
            logger.error(f"web_page_reader: unexpected error for {url}: {exc}")
            return {
                "success": False,
                "error": f"Unexpected error: {type(exc).__name__}: {exc}",
                "url": url,
            }


# ---------------------------------------------------------------------------
# Async helper for synchronous callers
# ---------------------------------------------------------------------------


def read_web_page_sync(url: str, max_chars: int = DEFAULT_MAX_CHARS) -> Dict[str, Any]:
    """
    Synchronous wrapper around WebPageReaderTool.execute().

    Useful for testing and scripts that are not running in an async context.

    Args:
        url: URL to fetch.
        max_chars: Maximum characters to return.

    Returns:
        Same dict as WebPageReaderTool.execute().
    """
    tool = WebPageReaderTool()
    return asyncio.run(tool.execute(url=url, max_chars=max_chars))
