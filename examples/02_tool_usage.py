"""
Example 02 — Tool Usage
========================
Demonstrates how to use each registered tool directly, and how to build
custom tool chains for specific tasks.

The tool registry is the single source of truth for all agent capabilities.
Every tool follows the same interface: async execute(**kwargs) -> dict.

Run this file directly:
    cd /path/to/citadel
    python3 examples/02_tool_usage.py

Author: Dev Team Lead
Built with Pride for Obex Blackvault
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.agents.tools.tool_registry import get_tool_registry
from backend.agents.tools.search_memory import SearchMemoryTool
from backend.agents.tools.web_page_reader import WebPageReaderTool
from backend.agents.tools.email_tool import EmailTool


# ─── Tool 1: Web Search (with memory) ────────────────────────────────────────

async def demo_web_search() -> None:
    """
    SearchMemoryTool wraps the DuckDuckGo search API with per-session
    deduplication. Duplicate queries return cached results instantly.

    Key behaviour: if cached=True in the result, the agent should call
    web_page_reader on the URLs instead of searching again.
    """
    print("\n── Web Search (with memory) ──")
    tool = SearchMemoryTool()

    # First search — hits the API
    result = await tool.execute(query="Snowflake Q4 2025 earnings revenue", max_results=3)
    print(f"  Cached: {result['cached']}  |  Results: {len(result.get('results', []))}")
    for r in result.get("results", [])[:2]:
        print(f"    • {r.get('title', '')[:60]}")
        print(f"      {r.get('url', '')}")

    # Same query again — returns from cache instantly
    result2 = await tool.execute(query="Snowflake Q4 2025 earnings revenue")
    print(f"\n  Second call — Cached: {result2['cached']}")
    if result2["cached"]:
        print(f"  Cache note: {result2.get('cache_note', '')}")

    print(f"\n  Total unique queries cached: {tool.cache_size()}")


# ─── Tool 2: Web Page Reader ──────────────────────────────────────────────────

async def demo_web_page_reader() -> None:
    """
    WebPageReaderTool fetches a URL and returns clean extracted text.
    Use this after web_search to read the full content of result pages.

    The tool handles:
    - SSL verification via the system CA bundle
    - JavaScript-heavy SPAs (returns best-effort text extraction)
    - Noise stripping (nav, ads, footers, scripts)
    - Content truncation to max_chars (default 8000)
    """
    print("\n── Web Page Reader ──")
    tool = WebPageReaderTool()

    result = await tool.execute(
        url="https://example.com",
        max_chars=500,
    )

    print(f"  Success:      {result['success']}")
    print(f"  Title:        {result.get('title', '—')}")
    print(f"  Content len:  {len(result.get('content', ''))}")
    print(f"  Content preview:\n    {result.get('content', '')[:200]}")


# ─── Tool 3: Python Executor ──────────────────────────────────────────────────

async def demo_python_executor() -> None:
    """
    PythonExecutorTool runs arbitrary Python code in a sandboxed subprocess.
    Agents use this for data analysis, calculations, and file processing.

    Security note: the executor runs in a subprocess with a timeout.
    It does NOT have network access by default.
    """
    print("\n── Python Executor ──")
    registry = get_tool_registry()
    tool = registry.get_tool("python_executor")
    if not tool:
        print("  python_executor not registered")
        return

    result = await tool.execute(
        code="""
import math

# Calculate compound interest
principal = 10_000
rate = 0.07
years = 10
future_value = principal * (1 + rate) ** years
print(f"$10,000 at 7% for 10 years = ${future_value:,.2f}")
print(f"That's {math.log(future_value/principal, 1+rate):.1f} years to double")
""",
        timeout=10,
    )

    print(f"  Success: {result['success']}")
    print(f"  Output:\n    {result.get('output', '').strip()}")


# ─── Tool 4: Calculator ───────────────────────────────────────────────────────

async def demo_calculator() -> None:
    """
    CalculatorTool evaluates mathematical expressions safely.
    Agents use this for quick arithmetic without spawning a subprocess.
    """
    print("\n── Calculator ──")
    registry = get_tool_registry()
    tool = registry.get_tool("calculator")
    if not tool:
        print("  calculator not registered")
        return

    expressions = [
        "2 ** 32",
        "1000000 * 0.15",
        "sqrt(144)",
        "(100000 / 12) * 1.07 ** 5",
    ]

    for expr in expressions:
        result = await tool.execute(expression=expr)
        print(f"  {expr:35s} = {result.get('result', result.get('error', '?'))}")


# ─── Tool 5: Email Sender ─────────────────────────────────────────────────────

async def demo_email_tool() -> None:
    """
    EmailTool sends emails via SMTP. Operates in dry-run mode when
    SMTP_USER and SMTP_PASSWORD env vars are not set.

    To enable live sending, set:
        export SMTP_HOST=smtp.gmail.com
        export SMTP_PORT=587
        export SMTP_USER=your@gmail.com
        export SMTP_PASSWORD=your-app-password
    """
    print("\n── Email Sender ──")
    tool = EmailTool()
    print(f"  Configured: {tool.is_configured} (dry_run={tool.dry_run})")

    result = await tool.execute(
        to="prospect@example.com",
        subject="Introducing Citadel AI — Autonomous Sales Intelligence",
        body=(
            "Hi,\n\n"
            "I wanted to reach out about Citadel AI — an autonomous agent platform "
            "that can research leads, qualify prospects, and generate personalised "
            "proposals at scale.\n\n"
            "Would you be open to a 15-minute call this week?\n\n"
            "Best,\nObex Blackvault\nCitadel AI"
        ),
    )

    print(f"  Success:    {result['success']}")
    print(f"  Dry run:    {result['dry_run']}")
    print(f"  Message ID: {result.get('message_id', '—')}")
    if result.get("note"):
        print(f"  Note:       {result['note']}")


# ─── Tool Chain: Search → Read → Summarise ───────────────────────────────────

async def demo_search_read_chain() -> None:
    """
    The correct two-step research pattern:
    1. Search to discover relevant URLs
    2. Read the pages to extract full content
    3. Synthesise the findings

    This is the pattern the few-shot library teaches agents to follow.
    Agents that skip step 2 and re-query instead will hit the cache and
    receive a reminder to use web_page_reader.
    """
    print("\n── Tool Chain: Search → Read → Synthesise ──")

    search = SearchMemoryTool()
    reader = WebPageReaderTool()

    # Step 1: Search
    search_result = await search.execute(
        query="OpenAI GPT-4 pricing per million tokens 2025",
        max_results=3,
    )
    print(f"  Step 1 — Search: {len(search_result.get('results', []))} results")

    # Step 2: Read the first result URL
    results = search_result.get("results", [])
    if results:
        url = results[0].get("url", "")
        print(f"  Step 2 — Reading: {url[:70]}")
        page = await reader.execute(url=url, max_chars=2000)
        print(f"  Step 2 — Content: {len(page.get('content', ''))} chars extracted")
        print(f"  Step 2 — Preview: {page.get('content', '')[:150].strip()}")
    else:
        print("  No results to read")


# ─── Main ─────────────────────────────────────────────────────────────────────

async def main() -> None:
    """Run all tool demos."""
    await demo_web_search()
    await demo_web_page_reader()
    await demo_python_executor()
    await demo_calculator()
    await demo_email_tool()
    await demo_search_read_chain()


if __name__ == "__main__":
    asyncio.run(main())
