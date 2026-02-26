"""
Default compliance rules for Omnipath V2.

Provides three core compliance rules:
1. ToolPermissionRule - Agent-tool permission checking
2. DataAccessRule - Data access justification
3. RateLimitRule - Rate limiting for expensive operations
"""

from typing import Dict, Any
from .models import ComplianceResult


# Agent-tool permission mapping
AGENT_TOOL_PERMISSIONS = {
    "researcher": ["web_search", "calculator"],
    "analyst": ["calculator", "python_executor"],
    "developer": ["python_executor", "file_reader", "file_writer"],
}


class ToolPermissionRule:
    """
    Check if agent has permission to use tool.
    
    Enforces agent-tool mappings to ensure agents only use
    tools appropriate for their capabilities.
    
    Example:
        rule = ToolPermissionRule()
        context = {
            "agent_type": "researcher",
            "tool_name": "web_search"
        }
        result = rule.check(context)
        # result.allowed = True
        
        context["tool_name"] = "file_writer"
        result = rule.check(context)
        # result.allowed = False
        # result.reason = "Agent 'researcher' not permitted to use 'file_writer'"
    """
    
    name = "tool_permission"
    description = "Verify agent has permission for tool"
    
    def check(self, context: Dict[str, Any]) -> ComplianceResult:
        """
        Check if agent type is permitted to use the tool.
        
        Args:
            context: Must contain:
                - agent_type: str
                - tool_name: str
        
        Returns:
            ComplianceResult.allow() if permitted
            ComplianceResult.block() if not permitted
        """
        agent_type = context.get("agent_type", "unknown")
        tool_name = context.get("tool_name", "unknown")
        
        # Get allowed tools for agent type
        allowed_tools = AGENT_TOOL_PERMISSIONS.get(agent_type, [])
        
        # Check permission
        if tool_name not in allowed_tools:
            return ComplianceResult.block(
                rule=self.name,
                reason=f"Agent '{agent_type}' not permitted to use '{tool_name}'"
            )
        
        return ComplianceResult.allow(self.name)


class DataAccessRule:
    """
    Check data access permissions.
    
    Requires mission justification for tools that access data
    (file_reader, database_query, etc.).
    
    Example:
        rule = DataAccessRule()
        context = {
            "tool_name": "file_reader",
            "mission_payload": {"task": "analyze logs"}
        }
        result = rule.check(context)
        # result.allowed = True
        
        context["mission_payload"] = {}
        result = rule.check(context)
        # result.allowed = False
        # result.reason = "Data access requires mission justification"
    """
    
    name = "data_access"
    description = "Verify data access is justified"
    
    # Tools that access data
    DATA_ACCESS_TOOLS = ["file_reader", "database_query"]
    
    def check(self, context: Dict[str, Any]) -> ComplianceResult:
        """
        Check if data access is justified by mission.
        
        Args:
            context: Must contain:
                - tool_name: str
                - mission_payload: Dict (optional)
        
        Returns:
            ComplianceResult.allow() if justified or not a data access tool
            ComplianceResult.block() if data access without justification
        """
        tool_name = context.get("tool_name", "unknown")
        
        # Only check data access tools
        if tool_name not in self.DATA_ACCESS_TOOLS:
            return ComplianceResult.allow(self.name)
        
        # Require mission justification
        mission = context.get("mission_payload", {})
        if not mission.get("task"):
            return ComplianceResult.block(
                rule=self.name,
                reason="Data access requires mission justification"
            )
        
        return ComplianceResult.allow(self.name)


class RateLimitRule:
    """
    Check rate limits for expensive operations.
    
    Enforces rate limits on expensive tools like web_search
    and python_executor to prevent abuse.
    
    Note: This is a simple in-memory implementation.
    For production, use Redis or similar.
    
    Example:
        rule = RateLimitRule()
        context = {
            "agent_id": "agent_123",
            "tool_name": "web_search"
        }
        
        # First 10 calls allowed
        for i in range(10):
            result = rule.check(context)
            # result.allowed = True
        
        # 11th call blocked
        result = rule.check(context)
        # result.allowed = False
        # result.reason = "Rate limit exceeded for 'web_search' (10/min)"
    """
    
    name = "rate_limit"
    description = "Enforce rate limits"
    
    # Rate limits per tool (calls per minute)
    RATE_LIMITS = {
        "web_search": 10,
        "python_executor": 5,
    }
    
    def __init__(self):
        """Initialize rate limit tracker."""
        self.usage_tracker: Dict[str, int] = {}
    
    def check(self, context: Dict[str, Any]) -> ComplianceResult:
        """
        Check if rate limit exceeded.
        
        Args:
            context: Must contain:
                - agent_id: str
                - tool_name: str
        
        Returns:
            ComplianceResult.allow() if under limit or not rate-limited
            ComplianceResult.block() if rate limit exceeded
        """
        agent_id = context.get("agent_id", "unknown")
        tool_name = context.get("tool_name", "unknown")
        
        # Only check rate-limited tools
        if tool_name not in self.RATE_LIMITS:
            return ComplianceResult.allow(self.name)
        
        # Check usage
        key = f"{agent_id}:{tool_name}"
        count = self.usage_tracker.get(key, 0)
        limit = self.RATE_LIMITS[tool_name]
        
        if count >= limit:
            return ComplianceResult.block(
                rule=self.name,
                reason=f"Rate limit exceeded for '{tool_name}' ({limit}/min)"
            )
        
        # Increment usage
        self.usage_tracker[key] = count + 1
        
        return ComplianceResult.allow(self.name)
    
    def reset(self, agent_id: str = None, tool_name: str = None) -> None:
        """
        Reset rate limit counters.
        
        Args:
            agent_id: If provided, reset only for this agent
            tool_name: If provided, reset only for this tool
        
        Example:
            # Reset all
            rule.reset()
            
            # Reset for specific agent
            rule.reset(agent_id="agent_123")
            
            # Reset for specific agent+tool
            rule.reset(agent_id="agent_123", tool_name="web_search")
        """
        if agent_id is None and tool_name is None:
            # Reset all
            self.usage_tracker.clear()
        elif agent_id and tool_name:
            # Reset specific agent+tool
            key = f"{agent_id}:{tool_name}"
            self.usage_tracker.pop(key, None)
        elif agent_id:
            # Reset all tools for agent
            keys_to_remove = [k for k in self.usage_tracker if k.startswith(f"{agent_id}:")]
            for key in keys_to_remove:
                self.usage_tracker.pop(key)
        elif tool_name:
            # Reset all agents for tool
            keys_to_remove = [k for k in self.usage_tracker if k.endswith(f":{tool_name}")]
            for key in keys_to_remove:
                self.usage_tracker.pop(key)
