"""
Model Context Protocol (MCP) Integration for Omnipath v5.0
Enables agents to use external tools and resources via MCP

Built with Pride for Obex Blackvault
"""

import json
import asyncio
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass
from enum import Enum

from backend.core.logging_config import get_logger, LoggerMixin


logger = get_logger(__name__)


# ============================================================================
# MCP Models
# ============================================================================

class MCPResourceType(str, Enum):
    """Types of MCP resources"""
    TOOL = "tool"
    PROMPT = "prompt"
    RESOURCE = "resource"


@dataclass
class MCPTool:
    """
    MCP tool definition
    """
    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Optional[Callable] = None


@dataclass
class MCPPrompt:
    """
    MCP prompt template
    """
    name: str
    description: str
    template: str
    arguments: List[str]


@dataclass
class MCPResource:
    """
    MCP resource (file, data, etc.)
    """
    uri: str
    name: str
    description: str
    mime_type: str


@dataclass
class MCPServer:
    """
    MCP server configuration
    """
    name: str
    command: str
    args: List[str]
    env: Optional[Dict[str, str]] = None


# ============================================================================
# MCP Client
# ============================================================================

class MCPClient(LoggerMixin):
    """
    Client for interacting with MCP servers
    """
    
    def __init__(self):
        """Initialize MCP client"""
        self._servers: Dict[str, MCPServer] = {}
        self._tools: Dict[str, MCPTool] = {}
        self._prompts: Dict[str, MCPPrompt] = {}
        self._resources: Dict[str, MCPResource] = {}
        self._processes: Dict[str, asyncio.subprocess.Process] = {}
    
    def register_server(self, server: MCPServer) -> None:
        """
        Register MCP server
        
        Args:
            server: Server configuration
        """
        self._servers[server.name] = server
        self.log_info(f"MCP server registered: {server.name}")
    
    async def start_server(self, server_name: str) -> bool:
        """
        Start MCP server process
        
        Args:
            server_name: Name of the server
        
        Returns:
            True if started successfully
        """
        server = self._servers.get(server_name)
        if not server:
            self.log_error(f"Server not found: {server_name}")
            return False
        
        try:
            # Start server process
            process = await asyncio.create_subprocess_exec(
                server.command,
                *server.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=server.env
            )
            
            self._processes[server_name] = process
            
            self.log_info(
                f"MCP server started: {server_name}",
                pid=process.pid
            )
            
            # Discover capabilities
            await self._discover_capabilities(server_name)
            
            return True
            
        except Exception as e:
            self.log_error(
                f"Failed to start MCP server: {server_name}",
                exc_info=True,
                error=str(e)
            )
            return False
    
    async def stop_server(self, server_name: str) -> None:
        """
        Stop MCP server process
        
        Args:
            server_name: Name of the server
        """
        process = self._processes.get(server_name)
        if process:
            process.terminate()
            await process.wait()
            del self._processes[server_name]
            
            self.log_info(f"MCP server stopped: {server_name}")
    
    async def _discover_capabilities(self, server_name: str) -> None:
        """
        Discover server capabilities
        
        Args:
            server_name: Name of the server
        """
        try:
            # Send initialize request
            response = await self._send_request(
                server_name,
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "omnipath",
                        "version": "5.0.0"
                    }
                }
            )
            
            # Extract capabilities
            capabilities = response.get("capabilities", {})
            
            # Discover tools
            if capabilities.get("tools"):
                await self._discover_tools(server_name)
            
            # Discover prompts
            if capabilities.get("prompts"):
                await self._discover_prompts(server_name)
            
            # Discover resources
            if capabilities.get("resources"):
                await self._discover_resources(server_name)
            
            self.log_info(
                f"Capabilities discovered for {server_name}",
                tools=len([t for t in self._tools if t.startswith(f"{server_name}:")]),
                prompts=len([p for p in self._prompts if p.startswith(f"{server_name}:")]),
                resources=len([r for r in self._resources if r.startswith(f"{server_name}:")])
            )
            
        except Exception as e:
            self.log_error(
                f"Failed to discover capabilities: {server_name}",
                exc_info=True,
                error=str(e)
            )
    
    async def _discover_tools(self, server_name: str) -> None:
        """
        Discover available tools
        
        Args:
            server_name: Name of the server
        """
        response = await self._send_request(server_name, "tools/list", {})
        
        tools = response.get("tools", [])
        for tool_data in tools:
            tool = MCPTool(
                name=tool_data["name"],
                description=tool_data.get("description", ""),
                input_schema=tool_data.get("inputSchema", {})
            )
            
            self._tools[f"{server_name}:{tool.name}"] = tool
            
            self.log_debug(f"Tool discovered: {tool.name}", server=server_name)
    
    async def _discover_prompts(self, server_name: str) -> None:
        """
        Discover available prompts
        
        Args:
            server_name: Name of the server
        """
        response = await self._send_request(server_name, "prompts/list", {})
        
        prompts = response.get("prompts", [])
        for prompt_data in prompts:
            prompt = MCPPrompt(
                name=prompt_data["name"],
                description=prompt_data.get("description", ""),
                template=prompt_data.get("template", ""),
                arguments=prompt_data.get("arguments", [])
            )
            
            self._prompts[f"{server_name}:{prompt.name}"] = prompt
            
            self.log_debug(f"Prompt discovered: {prompt.name}", server=server_name)
    
    async def _discover_resources(self, server_name: str) -> None:
        """
        Discover available resources
        
        Args:
            server_name: Name of the server
        """
        response = await self._send_request(server_name, "resources/list", {})
        
        resources = response.get("resources", [])
        for resource_data in resources:
            resource = MCPResource(
                uri=resource_data["uri"],
                name=resource_data.get("name", ""),
                description=resource_data.get("description", ""),
                mime_type=resource_data.get("mimeType", "text/plain")
            )
            
            self._resources[f"{server_name}:{resource.uri}"] = resource
            
            self.log_debug(f"Resource discovered: {resource.name}", server=server_name)
    
    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> Any:
        """
        Call MCP tool
        
        Args:
            tool_name: Name of the tool (format: "server:tool")
            arguments: Tool arguments
        
        Returns:
            Tool result
        """
        # Parse server and tool name
        if ":" not in tool_name:
            raise ValueError(f"Invalid tool name format: {tool_name}")
        
        server_name, tool = tool_name.split(":", 1)
        
        # Check if tool exists
        if tool_name not in self._tools:
            raise ValueError(f"Tool not found: {tool_name}")
        
        self.log_info(
            f"Calling tool: {tool}",
            server=server_name,
            arguments=arguments
        )
        
        try:
            # Send tool call request
            response = await self._send_request(
                server_name,
                "tools/call",
                {
                    "name": tool,
                    "arguments": arguments
                }
            )
            
            result = response.get("content", [])
            
            self.log_info(
                f"Tool call completed: {tool}",
                server=server_name
            )
            
            return result
            
        except Exception as e:
            self.log_error(
                f"Tool call failed: {tool}",
                exc_info=True,
                server=server_name,
                error=str(e)
            )
            raise
    
    async def get_prompt(
        self,
        prompt_name: str,
        arguments: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Get MCP prompt
        
        Args:
            prompt_name: Name of the prompt (format: "server:prompt")
            arguments: Prompt arguments
        
        Returns:
            Rendered prompt
        """
        # Parse server and prompt name
        if ":" not in prompt_name:
            raise ValueError(f"Invalid prompt name format: {prompt_name}")
        
        server_name, prompt = prompt_name.split(":", 1)
        
        # Check if prompt exists
        if prompt_name not in self._prompts:
            raise ValueError(f"Prompt not found: {prompt_name}")
        
        self.log_debug(
            f"Getting prompt: {prompt}",
            server=server_name
        )
        
        try:
            # Send prompt get request
            response = await self._send_request(
                server_name,
                "prompts/get",
                {
                    "name": prompt,
                    "arguments": arguments or {}
                }
            )
            
            messages = response.get("messages", [])
            
            # Combine messages into single prompt
            prompt_text = "\n\n".join(
                msg.get("content", {}).get("text", "")
                for msg in messages
            )
            
            return prompt_text
            
        except Exception as e:
            self.log_error(
                f"Failed to get prompt: {prompt}",
                exc_info=True,
                server=server_name,
                error=str(e)
            )
            raise
    
    async def read_resource(self, resource_uri: str) -> str:
        """
        Read MCP resource
        
        Args:
            resource_uri: URI of the resource (format: "server:uri")
        
        Returns:
            Resource content
        """
        # Parse server and URI
        if ":" not in resource_uri:
            raise ValueError(f"Invalid resource URI format: {resource_uri}")
        
        server_name, uri = resource_uri.split(":", 1)
        
        self.log_debug(
            f"Reading resource: {uri}",
            server=server_name
        )
        
        try:
            # Send resource read request
            response = await self._send_request(
                server_name,
                "resources/read",
                {
                    "uri": uri
                }
            )
            
            contents = response.get("contents", [])
            
            # Combine contents
            content = "\n".join(
                item.get("text", "")
                for item in contents
            )
            
            return content
            
        except Exception as e:
            self.log_error(
                f"Failed to read resource: {uri}",
                exc_info=True,
                server=server_name,
                error=str(e)
            )
            raise
    
    async def _send_request(
        self,
        server_name: str,
        method: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Send JSON-RPC request to MCP server
        
        Args:
            server_name: Name of the server
            method: RPC method
            params: Method parameters
        
        Returns:
            Response data
        """
        process = self._processes.get(server_name)
        if not process:
            raise RuntimeError(f"Server not running: {server_name}")
        
        # Create JSON-RPC request
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params
        }
        
        # Send request
        request_json = json.dumps(request) + "\n"
        process.stdin.write(request_json.encode())
        await process.stdin.drain()
        
        # Read response
        response_line = await process.stdout.readline()
        response = json.loads(response_line.decode())
        
        # Check for error
        if "error" in response:
            raise RuntimeError(
                f"MCP error: {response['error'].get('message', 'Unknown error')}"
            )
        
        return response.get("result", {})
    
    def list_tools(self) -> List[MCPTool]:
        """
        List all available tools
        
        Returns:
            List of tools
        """
        return list(self._tools.values())
    
    def list_prompts(self) -> List[MCPPrompt]:
        """
        List all available prompts
        
        Returns:
            List of prompts
        """
        return list(self._prompts.values())
    
    def list_resources(self) -> List[MCPResource]:
        """
        List all available resources
        
        Returns:
            List of resources
        """
        return list(self._resources.values())
    
    async def shutdown(self) -> None:
        """Shutdown all MCP servers"""
        for server_name in list(self._processes.keys()):
            await self.stop_server(server_name)
        
        self.log_info("All MCP servers shut down")


# ============================================================================
# MCP Integration for Agents
# ============================================================================

class MCPAgentIntegration(LoggerMixin):
    """
    Integration layer between agents and MCP
    """
    
    def __init__(self, mcp_client: MCPClient):
        """
        Initialize integration
        
        Args:
            mcp_client: MCP client instance
        """
        self.mcp_client = mcp_client
    
    async def get_available_tools_for_llm(self) -> List[Dict[str, Any]]:
        """
        Get tools formatted for LLM function calling
        
        Returns:
            List of tool definitions for LLM
        """
        tools = self.mcp_client.list_tools()
        
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema
                }
            }
            for tool in tools
        ]
    
    async def execute_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> str:
        """
        Execute tool call from LLM
        
        Args:
            tool_name: Name of the tool
            arguments: Tool arguments
        
        Returns:
            Tool result as string
        """
        self.log_info(
            f"Executing MCP tool from agent: {tool_name}",
            arguments=arguments
        )
        
        try:
            result = await self.mcp_client.call_tool(tool_name, arguments)
            
            # Convert result to string for LLM
            if isinstance(result, list):
                result_text = "\n".join(
                    item.get("text", str(item))
                    for item in result
                )
            else:
                result_text = str(result)
            
            return result_text
            
        except Exception as e:
            self.log_error(
                f"MCP tool execution failed: {tool_name}",
                exc_info=True,
                error=str(e)
            )
            return f"Error: {str(e)}"
