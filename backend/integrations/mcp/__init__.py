"""
MCP Integration Package for Omnipath v2

Public exports:
    MCPClient           — JSON-RPC client for MCP servers (subprocess transport)
    MCPAgentIntegration — High-level agent ↔ MCP bridge
    MCPToolBridge       — In-process bridge for ToolRegistry tools
    MCPServerRegistry   — Registry of server configurations
    setup_mcp           — Initialise MCP subsystem at app startup
    teardown_mcp        — Graceful shutdown
    get_mcp_client      — Access the active MCPClient singleton
    get_mcp_integration — Access the active MCPAgentIntegration singleton
    get_mcp_bridge      — Access the MCPToolBridge singleton
"""

from backend.integrations.mcp.mcp_client import (
    MCPClient,
    MCPAgentIntegration,
    MCPTool,
    MCPPrompt,
    MCPResource,
    MCPServer,
    MCPResourceType,
)
from backend.integrations.mcp.tool_bridge import (
    MCPToolBridge,
    MCPToolServer,
    get_mcp_tool_bridge,
)
from backend.integrations.mcp.server_registry import (
    MCPServerConfig,
    MCPServerRegistry,
    get_mcp_server_registry,
)
from backend.integrations.mcp.setup import (
    setup_mcp,
    teardown_mcp,
    get_mcp_client,
    get_mcp_integration,
    get_mcp_bridge,
)

__all__ = [
    # Client
    "MCPClient",
    "MCPAgentIntegration",
    "MCPTool",
    "MCPPrompt",
    "MCPResource",
    "MCPServer",
    "MCPResourceType",
    # Bridge
    "MCPToolBridge",
    "MCPToolServer",
    "get_mcp_tool_bridge",
    # Registry
    "MCPServerConfig",
    "MCPServerRegistry",
    "get_mcp_server_registry",
    # Setup
    "setup_mcp",
    "teardown_mcp",
    "get_mcp_client",
    "get_mcp_integration",
    "get_mcp_bridge",
]
