"""
SearchMemoryTool — Deduplicated Web Search
==========================================
Wraps the core WebSearchTool with a per-session in-memory cache that prevents
agents from issuing identical or near-identical queries in the same mission.

The cache is keyed by a normalised query string (lowercase, stripped, collapsed
whitespace).  If an agent submits a query that was already run in this session
the cached result is returned immediately with a ``cached: true`` flag so the
agent knows to move on to reading pages rather than re-querying.

Design decisions
----------------
* The cache is intentionally **not** shared across sessions / agent instances.
  Each ``SearchMemoryTool`` instance owns its own cache, so parallel missions
  do not interfere with each other.
* Cache entries never expire within a session — the assumption is that a single
  mission runs for minutes, not hours, so staleness is not a concern.
* The tool is a drop-in replacement for ``WebSearchTool`` and shares the same
  ``name`` / ``description`` / ``category`` interface so the LangChain tool
  schema is identical.

Author: Dev Team Lead
Built with Pride for Obex Blackvault
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from backend.agents.tools.base import BaseTool, ToolCategory
from backend.agents.tools.tool_registry import WebSearchTool

logger = logging.getLogger(__name__)


def _normalise(query: str) -> str:
    """Return a canonical form of *query* for cache-key comparison."""
    return re.sub(r"\s+", " ", query.lower().strip())


class SearchMemoryTool(BaseTool):
    """
    Deduplicated web search tool.

    Wraps ``WebSearchTool`` with an in-memory cache so that agents do not
    waste turns re-issuing queries they have already run in the same session.

    Attributes:
        _cache: Maps normalised query strings to their result dicts.
        _order: Insertion-ordered list of normalised queries (for inspection).
        _inner: The underlying ``WebSearchTool`` instance.
    """

    def __init__(self) -> None:
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._order: List[str] = []
        self._inner = WebSearchTool()

    # ------------------------------------------------------------------
    # BaseTool interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web for current information. "
            "Input: A search query string. "
            "Output: Top search results with titles, snippets, and URLs. "
            "Note: Duplicate queries within the same session are returned from "
            "cache instantly — if you receive cached=true, use web_page_reader "
            "to read the URLs instead of searching again."
        )

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.SEARCH

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute(  # type: ignore[override]
        self,
        query: str,
        max_results: int = 5,
    ) -> Dict[str, Any]:
        """
        Execute a web search, returning cached results for duplicate queries.

        Args:
            query: The search query string.
            max_results: Maximum number of results (ignored for cache hits).

        Returns:
            Standard search result dict, with an additional ``cached`` bool.
        """
        key = _normalise(query)

        if key in self._cache:
            logger.debug("search_memory: cache hit for query=%r", query)
            cached = dict(self._cache[key])
            cached["cached"] = True
            cached["cache_note"] = (
                "This query was already run. "
                "Use web_page_reader on the URLs above instead of searching again."
            )
            return cached

        result = await self._inner.execute(query, max_results=max_results)
        result["cached"] = False

        # Store in cache regardless of success so we do not retry failed queries
        self._cache[key] = result
        self._order.append(key)
        logger.debug("search_memory: cached query=%r (total=%d)", query, len(self._cache))
        return result

    # ------------------------------------------------------------------
    # Inspection helpers (useful for tests and mission reporting)
    # ------------------------------------------------------------------

    def cache_size(self) -> int:
        """Return the number of unique queries cached in this session."""
        return len(self._cache)

    def cached_queries(self) -> List[str]:
        """Return the list of cached queries in insertion order."""
        return list(self._order)

    def clear(self) -> None:
        """Clear the cache (useful between missions in long-running processes)."""
        self._cache.clear()
        self._order.clear()

    def get_cached(self, query: str) -> Optional[Dict[str, Any]]:
        """Return the cached result for *query*, or None if not cached."""
        return self._cache.get(_normalise(query))
