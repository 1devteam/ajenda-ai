"""
Playwright Browser Automation Tool for Omnipath v2 — Phase 3 (v6.2)

Provides browser automation capability to agents via the MCP ToolRegistry.
Supports navigation, clicking, typing, text extraction, and screenshots.

Enabled via environment variable:
    MCP_ENABLE_BROWSER=1

If Playwright is not installed or the env var is not set, the tool is
gracefully skipped — no startup failure.

Built with Pride for Obex Blackvault
"""

from __future__ import annotations

import base64
import os
from typing import Any, Dict, Optional

from backend.agents.tools.tool_registry import BaseTool, ToolCategory
from backend.core.logging_config import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Lazy import guard — Playwright is optional
# ---------------------------------------------------------------------------

_playwright_available: Optional[bool] = None


def _check_playwright() -> bool:
    """Return True if playwright async API is importable."""
    global _playwright_available
    if _playwright_available is None:
        try:
            from playwright.async_api import async_playwright  # noqa: F401

            _playwright_available = True
        except ImportError:
            _playwright_available = False
    return _playwright_available


# ---------------------------------------------------------------------------
# PlaywrightBrowserTool
# ---------------------------------------------------------------------------


class PlaywrightBrowserTool(BaseTool):
    """
    Browser automation tool using Playwright (async API).

    Supported actions:
        navigate   — Go to a URL and return page title + URL.
        get_text   — Extract all visible text from the current page.
        click      — Click an element matching a CSS selector.
        type_text  — Type text into an input matching a CSS selector.
        screenshot — Take a screenshot and return base64-encoded PNG.
        find       — Find elements matching a CSS selector and return text.

    Usage (in a mission prompt)::

        Use the browser tool to navigate to https://linkedin.com and
        extract the page title.

    Args:
        headless: Run browser in headless mode (default: True).
        timeout_ms: Default action timeout in milliseconds (default: 30000).
    """

    def __init__(
        self,
        headless: bool = True,
        timeout_ms: int = 30_000,
    ) -> None:
        self._headless = headless
        self._timeout_ms = timeout_ms

    # ------------------------------------------------------------------
    # BaseTool interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "browser"

    @property
    def description(self) -> str:
        return (
            "Automate a web browser to navigate pages, click elements, type text, "
            "extract content, and take screenshots. "
            "Input: action (navigate|get_text|click|type_text|screenshot|find), "
            "url (for navigate), selector (for click/type_text/find), "
            "text (for type_text). "
            "Output: result dict with extracted data or confirmation."
        )

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.COMMUNICATION

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute(
        self,
        action: str,
        url: Optional[str] = None,
        selector: Optional[str] = None,
        text: Optional[str] = None,
        wait_for: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute a browser action.

        Args:
            action:    One of navigate|get_text|click|type_text|screenshot|find.
            url:       Target URL (required for ``navigate``).
            selector:  CSS selector (required for click/type_text/find).
            text:      Text to type (required for ``type_text``).
            wait_for:  Optional CSS selector to wait for after action.

        Returns:
            Result dict with ``success``, ``action``, and action-specific data.
        """
        if not _check_playwright():
            return {
                "success": False,
                "error": "Playwright is not installed. Run: pip install playwright && playwright install chromium",
            }

        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=self._headless)
                try:
                    page = await browser.new_page()
                    page.set_default_timeout(self._timeout_ms)

                    result = await self._dispatch(page, action, url, selector, text, wait_for)
                finally:
                    await browser.close()

            return result

        except Exception as exc:
            logger.error(f"BrowserTool action '{action}' failed: {exc}", exc_info=True)
            return {"success": False, "action": action, "error": str(exc)}

    # ------------------------------------------------------------------
    # Action dispatch
    # ------------------------------------------------------------------

    async def _dispatch(
        self,
        page: Any,
        action: str,
        url: Optional[str],
        selector: Optional[str],
        text: Optional[str],
        wait_for: Optional[str],
    ) -> Dict[str, Any]:
        """Dispatch to the correct action handler."""
        handlers = {
            "navigate": self._navigate,
            "get_text": self._get_text,
            "click": self._click,
            "type_text": self._type_text,
            "screenshot": self._screenshot,
            "find": self._find,
        }

        handler = handlers.get(action)
        if handler is None:
            return {
                "success": False,
                "action": action,
                "error": f"Unknown action '{action}'. Valid: {list(handlers.keys())}",
            }

        return await handler(page, url=url, selector=selector, text=text, wait_for=wait_for)

    async def _navigate(
        self, page: Any, url: Optional[str] = None, **kwargs: Any
    ) -> Dict[str, Any]:
        """Navigate to a URL."""
        if not url:
            return {"success": False, "action": "navigate", "error": "url is required"}

        response = await page.goto(url, wait_until="domcontentloaded")
        title = await page.title()
        return {
            "success": True,
            "action": "navigate",
            "url": page.url,
            "title": title,
            "status": response.status if response else None,
        }

    async def _get_text(self, page: Any, **kwargs: Any) -> Dict[str, Any]:
        """Extract all visible text from the current page."""
        text = await page.evaluate("() => document.body.innerText")
        title = await page.title()
        return {
            "success": True,
            "action": "get_text",
            "url": page.url,
            "title": title,
            "text": text[:10_000],  # Limit to 10k chars to avoid LLM context overflow
            "truncated": len(text) > 10_000,
        }

    async def _click(
        self,
        page: Any,
        selector: Optional[str] = None,
        wait_for: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Click an element matching a CSS selector."""
        if not selector:
            return {"success": False, "action": "click", "error": "selector is required"}

        await page.click(selector)
        if wait_for:
            await page.wait_for_selector(wait_for)

        return {"success": True, "action": "click", "selector": selector, "url": page.url}

    async def _type_text(
        self,
        page: Any,
        selector: Optional[str] = None,
        text: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Type text into an input element."""
        if not selector:
            return {"success": False, "action": "type_text", "error": "selector is required"}
        if text is None:
            return {"success": False, "action": "type_text", "error": "text is required"}

        await page.fill(selector, text)
        return {
            "success": True,
            "action": "type_text",
            "selector": selector,
            "chars_typed": len(text),
        }

    async def _screenshot(self, page: Any, **kwargs: Any) -> Dict[str, Any]:
        """Take a screenshot and return base64-encoded PNG."""
        png_bytes = await page.screenshot(type="png")
        b64 = base64.b64encode(png_bytes).decode("utf-8")
        return {
            "success": True,
            "action": "screenshot",
            "url": page.url,
            "format": "png",
            "base64": b64,
            "size_bytes": len(png_bytes),
        }

    async def _find(
        self, page: Any, selector: Optional[str] = None, **kwargs: Any
    ) -> Dict[str, Any]:
        """Find elements matching a CSS selector and return their text."""
        if not selector:
            return {"success": False, "action": "find", "error": "selector is required"}

        elements = await page.query_selector_all(selector)
        texts = []
        for el in elements[:20]:  # Cap at 20 elements
            t = await el.inner_text()
            texts.append(t.strip())

        return {
            "success": True,
            "action": "find",
            "selector": selector,
            "count": len(elements),
            "texts": texts,
        }


# ---------------------------------------------------------------------------
# Factory function — only returns a tool if enabled
# ---------------------------------------------------------------------------


def make_browser_tool() -> Optional[PlaywrightBrowserTool]:
    """
    Return a PlaywrightBrowserTool if MCP_ENABLE_BROWSER is set.

    Returns:
        PlaywrightBrowserTool instance, or None if not enabled.
    """
    if not os.getenv("MCP_ENABLE_BROWSER"):
        return None

    if not _check_playwright():
        logger.warning(
            "MCP_ENABLE_BROWSER is set but playwright is not installed. "
            "Run: pip install playwright && playwright install chromium"
        )
        return None

    logger.info("Browser tool enabled (MCP_ENABLE_BROWSER=1)")
    return PlaywrightBrowserTool()
