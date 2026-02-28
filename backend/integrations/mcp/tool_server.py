"""
MCP Tool Server Entry Point for Omnipath v2

Runs a single ToolRegistry tool as an MCP stdio server.
Invoked by MCPServerRegistry as:
    python -m backend.integrations.mcp.tool_server <tool_name>

This module is the bridge between the MCPClient subprocess transport
and the in-process ToolRegistry implementations.

Built with Pride for Obex Blackvault
"""

from __future__ import annotations

import asyncio
import sys

from backend.agents.tools.tool_registry import get_tool_registry
from backend.integrations.mcp.tool_bridge import MCPToolServer


def main() -> None:
    """
    Entry point: read tool name from argv, run the MCP server.

    Usage:
        python -m backend.integrations.mcp.tool_server web_search
    """
    if len(sys.argv) < 2:
        print(
            "Usage: python -m backend.integrations.mcp.tool_server <tool_name>",
            file=sys.stderr,
        )
        sys.exit(1)

    tool_name = sys.argv[1]
    registry = get_tool_registry()
    tool = registry.get_tool(tool_name)

    if tool is None:
        print(f"Error: tool '{tool_name}' not found in registry.", file=sys.stderr)
        print(
            f"Available tools: {[t.name for t in registry.get_all_tools()]}",
            file=sys.stderr,
        )
        sys.exit(1)

    server = MCPToolServer(tool)
    asyncio.run(server.serve())


if __name__ == "__main__":
    main()
