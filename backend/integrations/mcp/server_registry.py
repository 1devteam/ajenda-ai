"""
MCP Server Registry for Omnipath v2
Manages built-in and external MCP server configurations.

The registry is the single source of truth for which MCP servers are
available in the system.  At startup, ``setup_mcp()`` (in setup.py)
reads this registry and starts each server via MCPClient.

Built with Pride for Obex Blackvault
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from backend.integrations.mcp.mcp_client import MCPServer
from backend.core.logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Server configuration dataclass
# ---------------------------------------------------------------------------

@dataclass
class MCPServerConfig:
    """
    Full configuration for an MCP server entry.

    Attributes:
        name:        Unique server name used as the key in MCPClient.
        description: Human-readable description of what this server provides.
        server:      MCPServer instance (command + args + optional env).
        enabled:     Whether to start this server at boot.  Defaults to True.
        required:    If True, startup fails when the server cannot be started.
    """

    name: str
    description: str
    server: MCPServer
    enabled: bool = True
    required: bool = False


# ---------------------------------------------------------------------------
# Built-in server definitions
# ---------------------------------------------------------------------------

def _make_builtin_servers() -> List[MCPServerConfig]:
    """
    Return the list of built-in MCP server configs.

    Each entry wraps one of the ToolRegistry tools as a standalone
    MCP server process (stdio transport).  The command is
    ``python -m backend.integrations.mcp.tool_server <tool_name>``,
    which is implemented in tool_server.py.
    """
    python_exe = shutil.which("python3.11") or shutil.which("python3") or "python"

    tool_servers = [
        ("web_search",       "DuckDuckGo web search — no API key required"),
        ("python_executor",  "Safe Python code execution in a sandboxed subprocess"),
        ("file_reader",      "Read files from allowed directories"),
        ("file_writer",      "Write files to allowed directories"),
        ("calculator",       "Safe mathematical expression evaluator"),
    ]

    configs: List[MCPServerConfig] = []
    for tool_name, description in tool_servers:
        configs.append(
            MCPServerConfig(
                name=f"builtin-{tool_name}",
                description=description,
                server=MCPServer(
                    name=f"builtin-{tool_name}",
                    command=python_exe,
                    args=["-m", "backend.integrations.mcp.tool_server", tool_name],
                    env={**os.environ},
                ),
                enabled=True,
                required=False,  # Built-ins are best-effort; bridge handles fallback
            )
        )

    return configs


def _make_external_servers() -> List[MCPServerConfig]:
    """
    Return optional external MCP server configs.

    These are disabled by default and require the corresponding binary
    to be installed (e.g. ``npx @modelcontextprotocol/server-filesystem``).
    Set the environment variable ``MCP_ENABLE_<NAME>=1`` to activate.
    """
    configs: List[MCPServerConfig] = []

    # Filesystem server (official MCP reference implementation)
    if os.getenv("MCP_ENABLE_FILESYSTEM"):
        npx = shutil.which("npx")
        if npx:
            configs.append(
                MCPServerConfig(
                    name="filesystem",
                    description="MCP filesystem server — read/write files via official MCP server",
                    server=MCPServer(
                        name="filesystem",
                        command=npx,
                        args=[
                            "-y",
                            "@modelcontextprotocol/server-filesystem",
                            "/tmp",
                        ],
                        env={**os.environ},
                    ),
                    enabled=True,
                    required=False,
                )
            )
        else:
            logger.warning("MCP_ENABLE_FILESYSTEM set but npx not found — skipping filesystem server")

    # Brave Search server
    if os.getenv("MCP_ENABLE_BRAVE_SEARCH") and os.getenv("BRAVE_API_KEY"):
        npx = shutil.which("npx")
        if npx:
            configs.append(
                MCPServerConfig(
                    name="brave-search",
                    description="Brave Search MCP server — web search with API key",
                    server=MCPServer(
                        name="brave-search",
                        command=npx,
                        args=["-y", "@modelcontextprotocol/server-brave-search"],
                        env={**os.environ, "BRAVE_API_KEY": os.environ["BRAVE_API_KEY"]},
                    ),
                    enabled=True,
                    required=False,
                )
            )

    return configs


# ---------------------------------------------------------------------------
# MCPServerRegistry
# ---------------------------------------------------------------------------

class MCPServerRegistry:
    """
    Registry of all MCP servers available to the Omnipath system.

    Usage::

        registry = MCPServerRegistry()
        for cfg in registry.get_enabled():
            await mcp_client.register_server(cfg.server)
            await mcp_client.start_server(cfg.name)
    """

    def __init__(self) -> None:
        self._configs: Dict[str, MCPServerConfig] = {}
        self._load_defaults()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _load_defaults(self) -> None:
        for cfg in _make_builtin_servers():
            self._configs[cfg.name] = cfg
        for cfg in _make_external_servers():
            self._configs[cfg.name] = cfg

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, config: MCPServerConfig) -> None:
        """
        Register a custom MCP server config.

        Args:
            config: Server configuration to register.
        """
        self._configs[config.name] = config
        logger.info(f"MCP server registered: {config.name}")

    def unregister(self, name: str) -> None:
        """
        Remove a server config by name.

        Args:
            name: Server name to remove.
        """
        self._configs.pop(name, None)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get(self, name: str) -> Optional[MCPServerConfig]:
        """Return a server config by name, or None if not found."""
        return self._configs.get(name)

    def get_all(self) -> List[MCPServerConfig]:
        """Return all registered server configs."""
        return list(self._configs.values())

    def get_enabled(self) -> List[MCPServerConfig]:
        """Return only enabled server configs."""
        return [c for c in self._configs.values() if c.enabled]

    def get_required(self) -> List[MCPServerConfig]:
        """Return configs marked as required."""
        return [c for c in self._configs.values() if c.required]

    def enable(self, name: str) -> None:
        """Enable a server by name."""
        if name in self._configs:
            self._configs[name].enabled = True

    def disable(self, name: str) -> None:
        """Disable a server by name."""
        if name in self._configs:
            self._configs[name].enabled = False

    def summary(self) -> Dict[str, bool]:
        """Return a ``{name: enabled}`` summary dict."""
        return {name: cfg.enabled for name, cfg in self._configs.items()}


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_registry: Optional[MCPServerRegistry] = None


def get_mcp_server_registry() -> MCPServerRegistry:
    """
    Return the module-level MCPServerRegistry singleton.
    Creates it on first call.
    """
    global _registry
    if _registry is None:
        _registry = MCPServerRegistry()
    return _registry
