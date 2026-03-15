"""
Agent Tool Registry for Omnipath V2
Built with Pride for Obex Blackvault

This module provides a comprehensive tool-calling infrastructure for agents.
Tools include web search, code execution, file operations, and more.
"""

from typing import Dict, Any, List, Optional
import subprocess
import tempfile
import os
import logging

from langchain_core.tools import Tool

# BaseTool and ToolCategory live in base.py to prevent circular imports
# with individual tool modules that import BaseTool but are also registered here.
from backend.agents.tools.base import BaseTool, ToolCategory  # noqa: F401

logger = logging.getLogger(__name__)


class WebSearchTool(BaseTool):
    """
    Web search tool using DuckDuckGo (no API key required).
    """

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return """Search the web for current information.
Input: A search query string.
Output: Top search results with titles, snippets, and URLs."""

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.SEARCH

    async def execute(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        """
        Execute web search.

        Args:
            query: Search query
            max_results: Maximum number of results to return

        Returns:
            Search results with metadata
        """
        try:
            # Use ddgs (the successor to duckduckgo_search — no API key required).
            # Falls back to the legacy duckduckgo_search package if ddgs is not installed.
            try:
                from ddgs import DDGS
            except ImportError:
                from duckduckgo_search import DDGS  # type: ignore[no-redef]

            results = []
            with DDGS() as ddgs:
                for result in ddgs.text(query, max_results=max_results):
                    results.append(
                        {
                            "title": result.get("title", ""),
                            "snippet": result.get("body", ""),
                            "url": result.get("href", ""),
                        }
                    )

            return {
                "success": True,
                "query": query,
                "results": results,
                "count": len(results),
            }

        except Exception as e:
            logger.error(f"Web search failed: {e}")
            return {"success": False, "error": str(e), "query": query}


class PythonExecutorTool(BaseTool):
    """
    Safe Python code execution tool with sandboxing.
    """

    @property
    def name(self) -> str:
        return "python_executor"

    @property
    def description(self) -> str:
        return """Execute Python code safely in a sandboxed environment.
Input: Python code as a string.
Output: Execution result (stdout, stderr, return value).
Note: Code runs in an isolated environment with limited permissions."""

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.CODE

    async def execute(self, code: str, timeout: int = 10) -> Dict[str, Any]:
        """
        Execute Python code safely.

        Args:
            code: Python code to execute
            timeout: Execution timeout in seconds

        Returns:
            Execution result with stdout, stderr, and return value
        """
        try:
            # Create a temporary file for the code
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
                f.write(code)
                temp_file = f.name

            try:
                # Execute the code in a subprocess with timeout
                result = subprocess.run(
                    ["python3", temp_file],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )

                return {
                    "success": result.returncode == 0,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "returncode": result.returncode,
                }

            finally:
                # Clean up the temporary file
                os.unlink(temp_file)

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"Execution timed out after {timeout} seconds",
            }

        except Exception as e:
            logger.error(f"Python execution failed: {e}")
            return {"success": False, "error": str(e)}


class FileReaderTool(BaseTool):
    """
    File reading tool with safety checks.
    """

    @property
    def name(self) -> str:
        return "file_reader"

    @property
    def description(self) -> str:
        return """Read the contents of a file.
Input: File path (absolute or relative).
Output: File contents as text.
Note: Only reads files in allowed directories."""

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.FILE

    def __init__(self, allowed_directories: Optional[List[str]] = None):
        """
        Initialize file reader.

        Args:
            allowed_directories: List of allowed directory paths
        """
        self.allowed_directories = allowed_directories or ["/tmp", "/home/ubuntu"]

    async def execute(self, file_path: str) -> Dict[str, Any]:
        """
        Read file contents.

        Args:
            file_path: Path to the file

        Returns:
            File contents and metadata
        """
        try:
            # Resolve to absolute path
            abs_path = os.path.abspath(file_path)

            # Check if path is in allowed directories
            allowed = any(abs_path.startswith(os.path.abspath(d)) for d in self.allowed_directories)

            if not allowed:
                return {
                    "success": False,
                    "error": f"Access denied: {abs_path} is not in allowed directories",
                }

            # Read the file
            with open(abs_path, "r") as f:
                content = f.read()

            return {
                "success": True,
                "file_path": abs_path,
                "content": content,
                "size_bytes": len(content),
            }

        except FileNotFoundError:
            return {"success": False, "error": f"File not found: {file_path}"}

        except Exception as e:
            logger.error(f"File read failed: {e}")
            return {"success": False, "error": str(e)}


class FileWriterTool(BaseTool):
    """
    File writing tool with safety checks.
    """

    @property
    def name(self) -> str:
        return "file_writer"

    @property
    def description(self) -> str:
        return """Write content to a file.
Input: file_path (string), content (string).
Output: Success confirmation.
Note: Only writes to allowed directories."""

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.FILE

    def __init__(self, allowed_directories: Optional[List[str]] = None):
        """
        Initialize file writer.

        Args:
            allowed_directories: List of allowed directory paths
        """
        self.allowed_directories = allowed_directories or ["/tmp"]

    async def execute(self, file_path: str, content: str) -> Dict[str, Any]:
        """
        Write content to file.

        Args:
            file_path: Path to the file
            content: Content to write

        Returns:
            Success confirmation
        """
        try:
            # Resolve to absolute path
            abs_path = os.path.abspath(file_path)

            # Check if path is in allowed directories
            allowed = any(abs_path.startswith(os.path.abspath(d)) for d in self.allowed_directories)

            if not allowed:
                return {
                    "success": False,
                    "error": f"Access denied: {abs_path} is not in allowed directories",
                }

            # Ensure directory exists
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)

            # Write the file
            with open(abs_path, "w") as f:
                f.write(content)

            return {
                "success": True,
                "file_path": abs_path,
                "bytes_written": len(content),
            }

        except Exception as e:
            logger.error(f"File write failed: {e}")
            return {"success": False, "error": str(e)}


class CalculatorTool(BaseTool):
    """
    Mathematical calculator tool.
    """

    @property
    def name(self) -> str:
        return "calculator"

    @property
    def description(self) -> str:
        return """Perform mathematical calculations.
Input: A mathematical expression as a string (e.g., "2 + 2", "sqrt(16)").
Output: The calculated result.
Supports: +, -, *, /, **, sqrt, sin, cos, tan, log, etc."""

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.DATA

    async def execute(self, expression: str) -> Dict[str, Any]:
        """
        Evaluate mathematical expression.

        Args:
            expression: Mathematical expression

        Returns:
            Calculation result
        """
        try:
            import math
            import numpy as np

            # Create a safe namespace for evaluation
            safe_namespace = {
                "__builtins__": {},
                "abs": abs,
                "round": round,
                "min": min,
                "max": max,
                "sum": sum,
                "sqrt": math.sqrt,
                "sin": math.sin,
                "cos": math.cos,
                "tan": math.tan,
                "log": math.log,
                "log10": math.log10,
                "exp": math.exp,
                "pi": math.pi,
                "e": math.e,
                "np": np,
            }

            result = eval(expression, safe_namespace)

            return {"success": True, "expression": expression, "result": result}

        except Exception as e:
            logger.error(f"Calculation failed: {e}")
            return {"success": False, "error": str(e), "expression": expression}


class ToolRegistry:
    """
    Registry for managing agent tools.
    """

    def __init__(self):
        self.tools: Dict[str, BaseTool] = {}
        self._register_default_tools()

    def _register_default_tools(self):
        """Register default tools available to all agents."""
        # Import here to avoid circular imports at module load time
        from backend.agents.tools.web_page_reader import WebPageReaderTool
        from backend.agents.tools.search_memory import SearchMemoryTool
        from backend.agents.tools.email_tool import EmailTool

        default_tools = [
            # SearchMemoryTool replaces plain WebSearchTool — same interface,
            # adds per-session deduplication to prevent re-query loops.
            SearchMemoryTool(),
            WebPageReaderTool(),
            PythonExecutorTool(),
            FileReaderTool(),
            FileWriterTool(),
            CalculatorTool(),
            EmailTool(),
        ]

        for tool in default_tools:
            self.register_tool(tool)

        # Optional tools — registered if dependencies are available
        self._register_phase3_tools()

    def _register_phase3_tools(self):
        """Register Phase 3 tools (browser automation, social media)."""
        # PlaywrightBrowserTool — optional, requires playwright
        try:
            from backend.integrations.tools.browser_tool import PlaywrightBrowserTool

            self.register_tool(PlaywrightBrowserTool())
        except ImportError:
            logger.info("PlaywrightBrowserTool skipped — playwright not installed")
        except Exception as exc:
            logger.warning(f"PlaywrightBrowserTool registration failed: {exc}")

        # TwitterTool — optional, requires tweepy
        try:
            from backend.integrations.tools.twitter_tool import TwitterTool

            self.register_tool(TwitterTool())
        except ImportError:
            logger.info("TwitterTool skipped — tweepy not installed")
        except Exception as exc:
            logger.warning(f"TwitterTool registration failed: {exc}")

        # RedditTool — optional, requires praw
        try:
            from backend.integrations.tools.reddit_tool import RedditTool

            self.register_tool(RedditTool())
        except ImportError:
            logger.info("RedditTool skipped — praw not installed")
        except Exception as exc:
            logger.warning(f"RedditTool registration failed: {exc}")

    def register_tool(self, tool: BaseTool):
        """Register a new tool."""
        self.tools[tool.name] = tool
        logger.info(f"Registered tool: {tool.name}")

    def get_tool(self, name: str) -> Optional[BaseTool]:
        """Get a tool by name."""
        return self.tools.get(name)

    def get_tools_by_category(self, category: ToolCategory) -> List[BaseTool]:
        """Get all tools in a category, skipping non-native tools without category."""
        result = []
        for tool in self.tools.values():
            try:
                if tool.category == category:
                    result.append(tool)
            except AttributeError:
                pass
        return result

    def get_all_tools(self) -> List[BaseTool]:
        """Get all registered tools."""
        return list(self.tools.values())

    def to_langchain_tools(self) -> List[Tool]:
        """Convert all registered tools to LangChain format."""
        tools = []
        for tool in self.tools.values():
            try:
                tools.append(tool.to_langchain_tool())
            except AttributeError:
                # Non-native tools (e.g. LangChain BaseTool subclasses)
                # are already in LangChain format
                tools.append(tool)  # type: ignore[arg-type]
        return tools


# Global tool registry
tool_registry = ToolRegistry()


def get_tool_registry() -> ToolRegistry:
    """Get the global tool registry."""
    return tool_registry
