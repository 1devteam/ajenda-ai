"""
Agent Tool Base Classes
=======================
Defines the BaseTool abstract class and ToolCategory enum.

Kept in a separate module to prevent circular imports between
tool_registry.py (which registers all tools) and individual tool
implementations (which import BaseTool).

Author: Dev Team Lead
Built with Pride for Obex Blackvault
"""

import asyncio
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict

from langchain_core.tools import Tool


class ToolCategory(str, Enum):
    """Categories of agent tools."""

    SEARCH = "search"
    CODE = "code"
    FILE = "file"
    DATA = "data"
    COMMUNICATION = "communication"


class BaseTool(ABC):
    """
    Abstract base class for all agent tools.

    Every tool must implement name, description, category, and execute().
    The execute() method is always async to support non-blocking I/O.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique tool name used for registration and lookup."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description shown to the LLM."""

    @property
    @abstractmethod
    def category(self) -> ToolCategory:
        """Functional category for grouping and filtering."""

    @abstractmethod
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        Execute the tool with the given arguments.

        Returns:
            Dict with at minimum a 'success' (bool) key.
            On failure, also includes an 'error' (str) key.
        """

    def to_langchain_tool(self) -> Tool:
        """Convert to LangChain Tool format for use in LangChain agent chains."""
        return Tool(
            name=self.name,
            description=self.description,
            func=lambda **kwargs: asyncio.run(self.execute(**kwargs)),
        )
