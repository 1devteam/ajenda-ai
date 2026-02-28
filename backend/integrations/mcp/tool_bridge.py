"""
MCP Tool Bridge for Omnipath v2
Bridges the ToolRegistry tools to the MCP protocol via stdio JSON-RPC.

Each BaseTool in the ToolRegistry is exposed as an MCP-compatible server,
allowing agents to discover and call tools through a uniform MCP interface.

Built with Pride for Obex Blackvault
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Dict, List, Optional

from backend.agents.tools.tool_registry import BaseTool, ToolRegistry, get_tool_registry
from backend.core.logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------


def _ok(request_id: Any, result: Any) -> Dict[str, Any]:
    """Build a JSON-RPC 2.0 success response."""
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _err(request_id: Any, code: int, message: str) -> Dict[str, Any]:
    """Build a JSON-RPC 2.0 error response."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


# ---------------------------------------------------------------------------
# In-process MCP server (stdio transport)
# ---------------------------------------------------------------------------


class MCPToolServer:
    """
    Lightweight MCP server that wraps a single BaseTool and speaks
    JSON-RPC 2.0 over stdin/stdout (the standard MCP stdio transport).

    Lifecycle:
        server = MCPToolServer(tool)
        await server.serve()   # blocks until stdin closes
    """

    PROTOCOL_VERSION = "2024-11-05"

    def __init__(self, tool: BaseTool) -> None:
        self.tool = tool
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def serve(self) -> None:
        """
        Read JSON-RPC requests from stdin, dispatch, write responses to stdout.
        Runs until stdin is closed (EOF).
        """
        loop = asyncio.get_event_loop()
        self._reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(self._reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        transport, _ = await loop.connect_write_pipe(asyncio.BaseProtocol, sys.stdout)
        self._writer = asyncio.StreamWriter(transport, protocol, self._reader, loop)

        while True:
            try:
                line = await self._reader.readline()
            except Exception:
                break
            if not line:
                break
            await self._handle_line(line)

    # ------------------------------------------------------------------
    # Internal dispatch
    # ------------------------------------------------------------------

    async def _handle_line(self, line: bytes) -> None:
        request: Dict[str, Any] = {}
        try:
            request = json.loads(line.decode("utf-8").strip())
        except json.JSONDecodeError as exc:
            await self._send(_err(None, -32700, f"Parse error: {exc}"))
            return

        req_id = request.get("id")
        method = request.get("method", "")
        params = request.get("params", {})

        if method == "initialize":
            await self._send(_ok(req_id, self._handle_initialize()))
        elif method == "tools/list":
            await self._send(_ok(req_id, self._handle_tools_list()))
        elif method == "tools/call":
            result = await self._handle_tools_call(params)
            await self._send(_ok(req_id, result))
        elif method == "prompts/list":
            await self._send(_ok(req_id, {"prompts": []}))
        elif method == "resources/list":
            await self._send(_ok(req_id, {"resources": []}))
        else:
            await self._send(_err(req_id, -32601, f"Method not found: {method}"))

    def _handle_initialize(self) -> Dict[str, Any]:
        return {
            "protocolVersion": self.PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {
                "name": f"omnipath-tool-{self.tool.name}",
                "version": "1.0.0",
            },
        }

    def _handle_tools_list(self) -> Dict[str, Any]:
        return {
            "tools": [
                {
                    "name": self.tool.name,
                    "description": self.tool.description,
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": True,
                    },
                }
            ]
        }

    async def _handle_tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        name = params.get("name", "")
        arguments = params.get("arguments", {})

        if name != self.tool.name:
            return {
                "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
                "isError": True,
            }

        try:
            result = await self.tool.execute(**arguments)
            return {
                "content": [{"type": "text", "text": json.dumps(result, default=str)}],
                "isError": False,
            }
        except Exception as exc:
            logger.error(f"Tool execution error [{self.tool.name}]: {exc}", exc_info=True)
            return {
                "content": [{"type": "text", "text": f"Error: {exc}"}],
                "isError": True,
            }

    async def _send(self, payload: Dict[str, Any]) -> None:
        line = json.dumps(payload) + "\n"
        if self._writer:
            self._writer.write(line.encode("utf-8"))
            await self._writer.drain()
        else:
            sys.stdout.write(line)
            sys.stdout.flush()


# ---------------------------------------------------------------------------
# MCPToolBridge — in-process bridge (no subprocess needed)
# ---------------------------------------------------------------------------


class MCPToolBridge:
    """
    In-process bridge that makes ToolRegistry tools available to MCPClient
    without spawning subprocesses.

    For each registered tool, the bridge:
    - Maintains a callable mapping
    - Exposes a ``call_tool(name, arguments)`` coroutine
    - Provides tool metadata in MCP format for LLM function-calling

    This is the preferred integration path for built-in tools.
    External MCP servers (filesystem, web, etc.) are handled by
    MCPServerRegistry and the standard MCPClient subprocess transport.
    """

    def __init__(self, registry: Optional[ToolRegistry] = None) -> None:
        self._registry: ToolRegistry = registry or get_tool_registry()

    # ------------------------------------------------------------------
    # Tool discovery
    # ------------------------------------------------------------------

    def list_tools_for_llm(self) -> List[Dict[str, Any]]:
        """
        Return tool definitions in OpenAI function-calling format.

        Returns:
            List of ``{"type": "function", "function": {...}}`` dicts.
        """
        result = []
        for tool in self._registry.get_all_tools():
            result.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "additionalProperties": True,
                        },
                    },
                }
            )
        return result

    def list_tools_as_mcp(self) -> List[Dict[str, Any]]:
        """
        Return tool definitions in MCP ``tools/list`` response format.

        Returns:
            List of MCP tool descriptor dicts.
        """
        result = []
        for tool in self._registry.get_all_tools():
            result.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": True,
                    },
                }
            )
        return result

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> str:
        """
        Execute a tool by name and return the result as a string.

        Args:
            tool_name: Registered tool name (e.g. ``"web_search"``).
            arguments: Keyword arguments forwarded to ``tool.execute()``.

        Returns:
            JSON-serialised result string, or an error message prefixed
            with ``"Error: "``.

        Raises:
            ValueError: If the tool is not registered.
        """
        tool = self._registry.get_tool(tool_name)
        if tool is None:
            raise ValueError(f"Tool not registered: {tool_name!r}")

        logger.info(f"MCPToolBridge: calling tool '{tool_name}'", extra={"arguments": arguments})

        try:
            result = await tool.execute(**arguments)
            return json.dumps(result, default=str)
        except Exception as exc:
            logger.error(
                f"MCPToolBridge: tool '{tool_name}' raised an exception",
                exc_info=True,
            )
            return f"Error: {exc}"

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def has_tool(self, tool_name: str) -> bool:
        """Return True if the tool is registered."""
        return self._registry.get_tool(tool_name) is not None

    def tool_names(self) -> List[str]:
        """Return a list of all registered tool names."""
        return [t.name for t in self._registry.get_all_tools()]


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_bridge: Optional[MCPToolBridge] = None


def get_mcp_tool_bridge() -> MCPToolBridge:
    """
    Return the module-level MCPToolBridge singleton.
    Creates it on first call using the global ToolRegistry.
    """
    global _bridge
    if _bridge is None:
        _bridge = MCPToolBridge()
    return _bridge
