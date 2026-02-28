"""
MCP Setup for Omnipath v2
Wires MCPClient, MCPToolBridge, and MCPServerRegistry into the FastAPI app.

Called from main.py lifespan:
    from backend.integrations.mcp.setup import setup_mcp, teardown_mcp
    await setup_mcp()
    ...
    await teardown_mcp()

Built with Pride for Obex Blackvault
"""

from __future__ import annotations

from typing import Optional

from backend.integrations.mcp.mcp_client import MCPClient, MCPAgentIntegration
from backend.integrations.mcp.tool_bridge import MCPToolBridge, get_mcp_tool_bridge
from backend.integrations.mcp.server_registry import (
    MCPServerRegistry,
    get_mcp_server_registry,
)
from backend.core.logging_config import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Module-level singletons (set by setup_mcp)
# ---------------------------------------------------------------------------

_mcp_client: Optional[MCPClient] = None
_mcp_integration: Optional[MCPAgentIntegration] = None
_mcp_bridge: Optional[MCPToolBridge] = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def setup_mcp() -> None:
    """
    Initialise the MCP subsystem.

    Steps:
    1. Create MCPClient and MCPToolBridge singletons.
    2. Register all enabled servers from MCPServerRegistry.
    3. Attempt to start each server; log warnings for non-required failures.
    4. Create MCPAgentIntegration wrapping the client.

    This function is idempotent — calling it a second time is a no-op.
    """
    global _mcp_client, _mcp_integration, _mcp_bridge

    if _mcp_client is not None:
        logger.debug("MCP already initialised — skipping setup_mcp()")
        return

    logger.info("Initialising MCP subsystem …")

    client = MCPClient()
    bridge = get_mcp_tool_bridge()
    registry: MCPServerRegistry = get_mcp_server_registry()

    started: list[str] = []
    failed: list[str] = []

    for cfg in registry.get_enabled():
        client.register_server(cfg.server)
        success = await client.start_server(cfg.name)
        if success:
            started.append(cfg.name)
        else:
            failed.append(cfg.name)
            if cfg.required:
                raise RuntimeError(
                    f"Required MCP server '{cfg.name}' failed to start. "
                    "Check that the command is installed and accessible."
                )
            logger.warning(
                f"Optional MCP server '{cfg.name}' failed to start — "
                "falling back to in-process MCPToolBridge for built-in tools."
            )

    integration = MCPAgentIntegration(client)

    _mcp_client = client
    _mcp_integration = integration
    _mcp_bridge = bridge

    logger.info(
        "MCP subsystem ready",
        extra={
            "started_servers": started,
            "failed_servers": failed,
            "bridge_tools": bridge.tool_names(),
        },
    )


async def teardown_mcp() -> None:
    """
    Gracefully shut down all MCP servers.
    Called from main.py lifespan on shutdown.
    """
    global _mcp_client, _mcp_integration, _mcp_bridge

    if _mcp_client is None:
        return

    logger.info("Shutting down MCP subsystem …")
    await _mcp_client.shutdown()

    _mcp_client = None
    _mcp_integration = None
    _mcp_bridge = None

    logger.info("MCP subsystem shut down.")


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------


def get_mcp_client() -> Optional[MCPClient]:
    """Return the active MCPClient, or None if MCP is not initialised."""
    return _mcp_client


def get_mcp_integration() -> Optional[MCPAgentIntegration]:
    """Return the active MCPAgentIntegration, or None if MCP is not initialised."""
    return _mcp_integration


def get_mcp_bridge() -> MCPToolBridge:
    """
    Return the MCPToolBridge.

    The bridge is always available (it wraps in-process tools) even if
    the MCP subprocess servers failed to start.
    """
    return get_mcp_tool_bridge()
