"""
Tests for WebPageReaderTool
===========================
Covers: URL validation, SSRF prevention, content extraction,
        truncation, error handling, and the sync wrapper.

All HTTP calls are mocked — no real network requests are made.

Author: Dev Team Lead
Built with Pride for Obex Blackvault
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure repo root is on path when running standalone
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.agents.tools.web_page_reader import (
    WebPageReaderTool,
    _extract_clean_text,
    _is_blocked_host,
    read_web_page_sync,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_response(
    status_code: int = 200,
    content_type: str = "text/html",
    text: str = "<html><head><title>Test</title></head><body><p>Hello world</p></body></html>",
    final_url: str = "https://example.com",
) -> MagicMock:
    """Build a mock httpx response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {"content-type": content_type}
    resp.text = text
    resp.url = MagicMock()
    resp.url.__str__ = lambda self: final_url
    return resp


def _make_async_client_context(response: MagicMock) -> MagicMock:
    """Wrap a mock response in an async context manager that mimics httpx.AsyncClient."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=response)

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


# ---------------------------------------------------------------------------
# Unit tests: _is_blocked_host
# ---------------------------------------------------------------------------


class TestIsBlockedHost:
    """Tests for the SSRF prevention guard."""

    def test_private_ipv4_10_range_is_blocked(self):
        """10.x.x.x addresses must be blocked."""
        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [(None, None, None, None, ("10.0.0.1", 0))]
            assert _is_blocked_host("internal.corp") is True

    def test_private_ipv4_192_168_range_is_blocked(self):
        """192.168.x.x addresses must be blocked."""
        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [(None, None, None, None, ("192.168.1.100", 0))]
            assert _is_blocked_host("router.local") is True

    def test_loopback_is_blocked(self):
        """127.0.0.1 loopback must be blocked."""
        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [(None, None, None, None, ("127.0.0.1", 0))]
            assert _is_blocked_host("localhost") is True

    def test_link_local_is_blocked(self):
        """169.254.x.x link-local addresses must be blocked."""
        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [(None, None, None, None, ("169.254.169.254", 0))]
            assert _is_blocked_host("metadata.internal") is True

    def test_public_ip_is_allowed(self):
        """Public IP addresses must not be blocked."""
        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [(None, None, None, None, ("93.184.216.34", 0))]
            assert _is_blocked_host("example.com") is False

    def test_dns_failure_blocks_host(self):
        """If DNS resolution fails, the host must be blocked."""
        import socket

        with patch("socket.getaddrinfo", side_effect=socket.gaierror("NXDOMAIN")):
            assert _is_blocked_host("nonexistent.invalid") is True


# ---------------------------------------------------------------------------
# Unit tests: _extract_clean_text
# ---------------------------------------------------------------------------


class TestExtractCleanText:
    """Tests for the HTML → clean text extractor."""

    def test_extracts_title(self):
        html = "<html><head><title>My Page</title></head><body><p>Content</p></body></html>"
        result = _extract_clean_text(html, "https://example.com")
        assert result["title"] == "My Page"

    def test_extracts_body_text(self):
        html = "<html><body><p>Hello world</p></body></html>"
        result = _extract_clean_text(html, "https://example.com")
        assert "Hello world" in result["content"]

    def test_strips_script_tags(self):
        html = "<html><body><script>alert('xss')</script><p>Real content</p></body></html>"
        result = _extract_clean_text(html, "https://example.com")
        assert "alert" not in result["content"]
        assert "Real content" in result["content"]

    def test_strips_style_tags(self):
        html = (
            "<html><head><style>body { color: red; }</style></head>"
            "<body><p>Text</p></body></html>"
        )
        result = _extract_clean_text(html, "https://example.com")
        assert "color" not in result["content"]
        assert "Text" in result["content"]

    def test_strips_nav_tags(self):
        html = "<html><body><nav>Menu items</nav><main><p>Article text</p></main></body></html>"
        result = _extract_clean_text(html, "https://example.com")
        assert "Menu items" not in result["content"]
        assert "Article text" in result["content"]

    def test_handles_empty_html(self):
        result = _extract_clean_text("", "https://example.com")
        assert result["title"] == ""
        assert result["content"] == ""

    def test_handles_malformed_html(self):
        """Should not raise on malformed HTML."""
        html = "<html><body><p>Unclosed paragraph<div>Nested</body>"
        result = _extract_clean_text(html, "https://example.com")
        assert isinstance(result["content"], str)

    def test_collapses_excessive_blank_lines(self):
        html = "<html><body><p>Line 1</p>\n\n\n\n\n<p>Line 2</p></body></html>"
        result = _extract_clean_text(html, "https://example.com")
        # Should not have more than 2 consecutive newlines
        assert "\n\n\n" not in result["content"]

    def test_prefers_main_content_area(self):
        html = (
            "<html><body>"
            "<nav>Navigation noise</nav>"
            "<main><article><p>The real article content</p></article></main>"
            "<footer>Footer noise</footer>"
            "</body></html>"
        )
        result = _extract_clean_text(html, "https://example.com")
        assert "real article content" in result["content"]


# ---------------------------------------------------------------------------
# Integration tests: WebPageReaderTool.execute()
# ---------------------------------------------------------------------------


class TestWebPageReaderToolExecute:
    """Tests for the full execute() method."""

    @pytest.fixture
    def tool(self):
        return WebPageReaderTool()

    # --- Input validation ---

    @pytest.mark.asyncio
    async def test_rejects_empty_url(self, tool):
        result = await tool.execute(url="")
        assert result["success"] is False
        assert "non-empty string" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_non_http_scheme(self, tool):
        result = await tool.execute(url="ftp://example.com")
        assert result["success"] is False
        assert "ftp" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_file_scheme(self, tool):
        result = await tool.execute(url="file:///etc/passwd")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_rejects_private_ip_ssrf(self, tool):
        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [(None, None, None, None, ("10.0.0.1", 0))]
            result = await tool.execute(url="http://internal.corp/secret")
        assert result["success"] is False
        assert "private" in result["error"].lower() or "denied" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_rejects_blocked_domain(self):
        tool = WebPageReaderTool(blocked_domains=["evil.com"])
        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [(None, None, None, None, ("1.2.3.4", 0))]
            result = await tool.execute(url="https://evil.com/page")
        assert result["success"] is False
        assert "blocked" in result["error"].lower()

    # --- Successful fetch ---

    @pytest.mark.asyncio
    async def test_successful_fetch_returns_content(self, tool):
        mock_resp = _make_mock_response(
            text=(
                "<html><head><title>Test Page</title></head>"
                "<body><p>Hello world</p></body></html>"
            ),
            final_url="https://example.com",
        )
        ctx = _make_async_client_context(mock_resp)

        with patch("socket.getaddrinfo") as mock_gai, patch("httpx.AsyncClient", return_value=ctx):
            mock_gai.return_value = [(None, None, None, None, ("93.184.216.34", 0))]
            result = await tool.execute(url="https://example.com")

        assert result["success"] is True
        assert result["title"] == "Test Page"
        assert "Hello world" in result["content"]
        assert result["status_code"] == 200
        assert result["truncated"] is False

    @pytest.mark.asyncio
    async def test_truncates_long_content(self, tool):
        long_text = "A" * 20_000
        html = f"<html><body><p>{long_text}</p></body></html>"
        mock_resp = _make_mock_response(text=html)
        ctx = _make_async_client_context(mock_resp)

        with patch("socket.getaddrinfo") as mock_gai, patch("httpx.AsyncClient", return_value=ctx):
            mock_gai.return_value = [(None, None, None, None, ("93.184.216.34", 0))]
            result = await tool.execute(url="https://example.com", max_chars=1000)

        assert result["success"] is True
        assert result["truncated"] is True
        # 1000 chars + truncation notice appended
        assert result["char_count"] <= 1100

    @pytest.mark.asyncio
    async def test_max_chars_ceiling_enforced(self, tool):
        """Requesting more than MAX_CHARS_CEILING should be silently clamped."""
        mock_resp = _make_mock_response(text="<html><body><p>Short</p></body></html>")
        ctx = _make_async_client_context(mock_resp)

        with patch("socket.getaddrinfo") as mock_gai, patch("httpx.AsyncClient", return_value=ctx):
            mock_gai.return_value = [(None, None, None, None, ("93.184.216.34", 0))]
            # Request more than the ceiling — should not raise
            result = await tool.execute(url="https://example.com", max_chars=999_999)

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_follows_redirects_and_returns_final_url(self, tool):
        mock_resp = _make_mock_response(final_url="https://example.com/final")
        ctx = _make_async_client_context(mock_resp)

        with patch("socket.getaddrinfo") as mock_gai, patch("httpx.AsyncClient", return_value=ctx):
            mock_gai.return_value = [(None, None, None, None, ("93.184.216.34", 0))]
            result = await tool.execute(url="https://example.com/redirect")

        assert result["success"] is True
        assert result["url"] == "https://example.com/final"  # noqa: E501

    # --- HTTP error handling ---

    @pytest.mark.asyncio
    async def test_returns_failure_on_404(self, tool):
        mock_resp = _make_mock_response(status_code=404)
        ctx = _make_async_client_context(mock_resp)

        with patch("socket.getaddrinfo") as mock_gai, patch("httpx.AsyncClient", return_value=ctx):
            mock_gai.return_value = [(None, None, None, None, ("93.184.216.34", 0))]
            result = await tool.execute(url="https://example.com/missing")

        assert result["success"] is False
        assert "404" in result["error"]

    @pytest.mark.asyncio
    async def test_returns_failure_on_500(self, tool):
        mock_resp = _make_mock_response(status_code=500)
        ctx = _make_async_client_context(mock_resp)

        with patch("socket.getaddrinfo") as mock_gai, patch("httpx.AsyncClient", return_value=ctx):
            mock_gai.return_value = [(None, None, None, None, ("93.184.216.34", 0))]
            result = await tool.execute(url="https://example.com/error")

        assert result["success"] is False
        assert "500" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_non_html_content_type(self, tool):
        mock_resp = _make_mock_response(
            content_type="application/pdf",
            text="%PDF-1.4",
        )
        ctx = _make_async_client_context(mock_resp)

        with patch("socket.getaddrinfo") as mock_gai, patch("httpx.AsyncClient", return_value=ctx):
            mock_gai.return_value = [(None, None, None, None, ("93.184.216.34", 0))]
            result = await tool.execute(url="https://example.com/doc.pdf")

        assert result["success"] is False
        assert "content type" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_handles_timeout(self, tool):
        import httpx as _httpx

        ctx = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=_httpx.TimeoutException("timed out"))
        ctx.__aenter__ = AsyncMock(return_value=mock_client)
        ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("socket.getaddrinfo") as mock_gai, patch("httpx.AsyncClient", return_value=ctx):
            mock_gai.return_value = [(None, None, None, None, ("93.184.216.34", 0))]
            result = await tool.execute(url="https://slow.example.com")

        assert result["success"] is False
        assert "timed out" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_handles_too_many_redirects(self, tool):
        import httpx as _httpx

        ctx = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=_httpx.TooManyRedirects("too many"))
        ctx.__aenter__ = AsyncMock(return_value=mock_client)
        ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("socket.getaddrinfo") as mock_gai, patch("httpx.AsyncClient", return_value=ctx):
            mock_gai.return_value = [(None, None, None, None, ("93.184.216.34", 0))]
            result = await tool.execute(url="https://redirect-loop.example.com")

        assert result["success"] is False
        assert "redirect" in result["error"].lower()

    # --- Tool metadata ---

    def test_tool_name(self, tool):
        assert tool.name == "web_page_reader"

    def test_tool_category_is_search(self, tool):
        from backend.agents.tools.tool_registry import ToolCategory

        assert tool.category == ToolCategory.SEARCH

    def test_description_mentions_workflow(self, tool):
        assert "web_search" in tool.description
        assert "web_page_reader" in tool.description


# ---------------------------------------------------------------------------
# Tests: read_web_page_sync wrapper
# ---------------------------------------------------------------------------


class TestReadWebPageSync:
    """Tests for the synchronous wrapper."""

    def test_sync_wrapper_returns_success(self):
        mock_resp = _make_mock_response(
            text="<html><head><title>Sync Test</title></head><body><p>Works</p></body></html>",
        )
        ctx = _make_async_client_context(mock_resp)

        with patch("socket.getaddrinfo") as mock_gai, patch("httpx.AsyncClient", return_value=ctx):
            mock_gai.return_value = [(None, None, None, None, ("93.184.216.34", 0))]
            result = read_web_page_sync("https://example.com")

        assert result["success"] is True
        assert result["title"] == "Sync Test"

    def test_sync_wrapper_propagates_errors(self):
        result = read_web_page_sync("ftp://invalid.scheme.com")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# Tests: ToolRegistry integration
# ---------------------------------------------------------------------------


class TestToolRegistryIntegration:
    """Verify WebPageReaderTool is properly registered in the global registry."""

    def test_web_page_reader_is_registered(self):
        from backend.agents.tools.tool_registry import get_tool_registry

        registry = get_tool_registry()
        assert "web_page_reader" in registry.tools

    def test_web_page_reader_is_retrievable(self):
        from backend.agents.tools.tool_registry import get_tool_registry

        registry = get_tool_registry()
        tool = registry.get_tool("web_page_reader")
        assert tool is not None
        assert isinstance(tool, WebPageReaderTool)

    def test_web_page_reader_in_search_category(self):
        from backend.agents.tools.tool_registry import ToolCategory, get_tool_registry

        registry = get_tool_registry()
        search_tools = registry.get_tools_by_category(ToolCategory.SEARCH)
        tool_names = [t.name for t in search_tools]
        assert "web_page_reader" in tool_names
        assert "web_search" in tool_names
