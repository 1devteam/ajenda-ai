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


class CostLimitRule:
    """
    Check cost limits for expensive operations.
    
    Tracks cumulative costs and blocks when budget exceeded.
    Prevents runaway spending from LLM/API calls.
    
    Note: This is a simple in-memory implementation.
    For production, use Redis or database for persistence.
    
    Example:
        rule = CostLimitRule()
        context = {
            "agent_id": "agent_123",
            "tool_name": "web_search",
            "estimated_cost_usd": 0.05,
            "tenant_id": "tenant_456"
        }
        
        # First $10 allowed
        for i in range(200):  # 200 * $0.05 = $10
            result = rule.check(context)
            # result.allowed = True
        
        # Next call blocked
        result = rule.check(context)
        # result.allowed = False
        # result.reason = "Cost limit exceeded for agent 'agent_123' ($10.00/$10.00)"
    """
    
    name = "cost_limit"
    description = "Enforce cost limits"
    
    # Cost limits per agent (USD)
    AGENT_COST_LIMITS = {
        "researcher": 10.0,  # $10/day
        "analyst": 20.0,     # $20/day
        "developer": 15.0,   # $15/day
    }
    
    # Default cost estimates per tool (USD)
    TOOL_COST_ESTIMATES = {
        "web_search": 0.05,
        "python_executor": 0.01,
        "llm_call": 0.10,
    }
    
    def __init__(self):
        """Initialize cost tracker."""
        self.cost_tracker: Dict[str, float] = {}
    
    def check(self, context: Dict[str, Any]) -> ComplianceResult:
        """
        Check if cost limit exceeded.
        
        Args:
            context: Must contain:
                - agent_id: str
                - agent_type: str (optional, for limit lookup)
                - tool_name: str
                - estimated_cost_usd: float (optional, uses default if not provided)
        
        Returns:
            ComplianceResult.allow() if under limit
            ComplianceResult.block() if cost limit exceeded
        """
        agent_id = context.get("agent_id", "unknown")
        agent_type = context.get("agent_type", "unknown")
        tool_name = context.get("tool_name", "unknown")
        
        # Get cost estimate
        estimated_cost = context.get(
            "estimated_cost_usd",
            self.TOOL_COST_ESTIMATES.get(tool_name, 0.0)
        )
        
        # Get cost limit for agent type
        cost_limit = self.AGENT_COST_LIMITS.get(agent_type, 5.0)  # Default $5
        
        # Check current cost
        current_cost = self.cost_tracker.get(agent_id, 0.0)
        new_cost = current_cost + estimated_cost
        
        if new_cost > cost_limit:
            return ComplianceResult.block(
                rule=self.name,
                reason=f"Cost limit exceeded for agent '{agent_id}' (${new_cost:.2f}/${cost_limit:.2f})"
            )
        
        # Increment cost
        self.cost_tracker[agent_id] = new_cost
        
        return ComplianceResult.allow(self.name)
    
    def reset(self, agent_id: str = None) -> None:
        """
        Reset cost counters.
        
        Args:
            agent_id: If provided, reset only for this agent
        
        Example:
            # Reset all
            rule.reset()
            
            # Reset for specific agent
            rule.reset(agent_id="agent_123")
        """
        if agent_id is None:
            # Reset all
            self.cost_tracker.clear()
        else:
            # Reset specific agent
            self.cost_tracker.pop(agent_id, None)
    
    def get_cost(self, agent_id: str) -> float:
        """
        Get current cost for agent.
        
        Args:
            agent_id: Agent ID
        
        Returns:
            Current cumulative cost in USD
        """
        return self.cost_tracker.get(agent_id, 0.0)


class DataPrivacyRule:
    """
    Check for PII/sensitive data in parameters.
    
    Prevents accidental exposure of personally identifiable information
    (PII) and sensitive data through tool parameters.
    
    Detects patterns for:
    - Email addresses
    - Credit card numbers
    - Social Security Numbers (SSN)
    - Phone numbers
    - API keys/tokens
    
    Example:
        rule = DataPrivacyRule()
        context = {
            "tool_name": "web_search",
            "parameters": {"query": "john.doe@company.com"}
        }
        result = rule.check(context)
        # result.allowed = False
        # result.reason = "PII detected: email address in parameters"
        
        context["parameters"] = {"query": "machine learning"}
        result = rule.check(context)
        # result.allowed = True
    """
    
    name = "data_privacy"
    description = "Prevent PII exposure"
    
    # PII patterns (regex)
    import re
    
    PII_PATTERNS = {
        "email": re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
        "credit_card": re.compile(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b'),
        "ssn": re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),
        "phone": re.compile(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'),
        "api_key": re.compile(r'\b(sk_live_|pk_live_|api_key_)[A-Za-z0-9]{20,}\b'),  # API key prefix pattern
    }
    
    def check(self, context: Dict[str, Any]) -> ComplianceResult:
        """
        Check parameters for PII patterns.
        
        Args:
            context: Must contain:
                - parameters: Dict (tool parameters to check)
        
        Returns:
            ComplianceResult.allow() if no PII detected
            ComplianceResult.block() if PII detected
        """
        parameters = context.get("parameters", {})
        
        # Convert parameters to string for pattern matching
        param_str = str(parameters)
        
        # Check each PII pattern
        for pii_type, pattern in self.PII_PATTERNS.items():
            if pattern.search(param_str):
                return ComplianceResult.block(
                    rule=self.name,
                    reason=f"PII detected: {pii_type} in parameters"
                )
        
        return ComplianceResult.allow(self.name)


class ApprovalRequiredRule:
    """
    Require human approval for sensitive operations.
    
    Marks certain tools/operations as requiring explicit human approval
    before execution. Supports approval workflows for compliance.
    
    Note: This rule returns a special "requires_approval" status.
    The compliance engine should handle this appropriately.
    
    Example:
        rule = ApprovalRequiredRule()
        context = {
            "tool_name": "file_writer",
            "parameters": {"path": "/prod/config.yaml"}
        }
        result = rule.check(context)
        # result.allowed = False
        # result.reason = "Tool 'file_writer' requires approval"
        
        context["tool_name"] = "web_search"
        result = rule.check(context)
        # result.allowed = True
    """
    
    name = "approval_required"
    description = "Require approval for sensitive operations"
    
    # Tools requiring approval
    APPROVAL_REQUIRED_TOOLS = [
        "file_writer",
        "database_query",
        "api_caller",
    ]
    
    # Sensitive paths requiring approval
    SENSITIVE_PATH_PATTERNS = [
        "/prod/",
        "/production/",
        "/config/",
        ".env",
    ]
    
    def check(self, context: Dict[str, Any]) -> ComplianceResult:
        """
        Check if operation requires approval.
        
        Args:
            context: Must contain:
                - tool_name: str
                - parameters: Dict (optional, for path checking)
        
        Returns:
            ComplianceResult.allow() if no approval required
            ComplianceResult.block() with "requires_approval" reason if approval needed
        """
        tool_name = context.get("tool_name", "unknown")
        parameters = context.get("parameters", {})
        
        # Check if tool requires approval
        if tool_name in self.APPROVAL_REQUIRED_TOOLS:
            # Check for sensitive paths
            path = parameters.get("path", "")
            if any(pattern in path for pattern in self.SENSITIVE_PATH_PATTERNS):
                return ComplianceResult.block(
                    rule=self.name,
                    reason=f"Sensitive path '{path}' requires approval"
                )
            
            return ComplianceResult.block(
                rule=self.name,
                reason=f"Tool '{tool_name}' requires approval"
            )
        
        return ComplianceResult.allow(self.name)


class TenantIsolationRule:
    """
    Enforce multi-tenant data isolation.
    
    Prevents agents from accessing data belonging to other tenants.
    Critical for SaaS security and compliance.
    
    Example:
        rule = TenantIsolationRule()
        context = {
            "agent_id": "agent_123",
            "tenant_id": "tenant_456",
            "tool_name": "file_reader",
            "parameters": {"path": "/tenant_456/data.json"}
        }
        result = rule.check(context)
        # result.allowed = True
        
        context["parameters"] = {"path": "/tenant_789/data.json"}
        result = rule.check(context)
        # result.allowed = False
        # result.reason = "Cross-tenant access denied: agent belongs to 'tenant_456', accessing 'tenant_789'"
    """
    
    name = "tenant_isolation"
    description = "Enforce tenant isolation"
    
    # Tools that access tenant data
    TENANT_DATA_TOOLS = [
        "file_reader",
        "file_writer",
        "database_query",
    ]
    
    def check(self, context: Dict[str, Any]) -> ComplianceResult:
        """
        Check tenant isolation.
        
        Args:
            context: Must contain:
                - tenant_id: str (agent's tenant)
                - tool_name: str
                - parameters: Dict (optional, for path/resource checking)
        
        Returns:
            ComplianceResult.allow() if same tenant or not tenant-scoped
            ComplianceResult.block() if cross-tenant access detected
        """
        tool_name = context.get("tool_name", "unknown")
        
        # Only check tenant data tools
        if tool_name not in self.TENANT_DATA_TOOLS:
            return ComplianceResult.allow(self.name)
        
        agent_tenant = context.get("tenant_id", "unknown")
        parameters = context.get("parameters", {})
        
        # Check path for tenant ID
        path = parameters.get("path", "")
        if path:
            # Extract tenant ID from path (assumes /tenant_<id>/ format)
            import re
            match = re.search(r'/(tenant_[^/]+)(?:/|$)', path)
            if match:
                resource_tenant = match.group(1)
                if resource_tenant != agent_tenant:
                    return ComplianceResult.block(
                        rule=self.name,
                        reason=f"Cross-tenant access denied: agent belongs to '{agent_tenant}', accessing '{resource_tenant}'"
                    )
        
        # Check query for tenant_id parameter
        query = parameters.get("query", "")
        if "tenant_id" in query:
            # Simple check - in production, parse SQL properly
            if agent_tenant not in query:
                return ComplianceResult.block(
                    rule=self.name,
                    reason=f"Cross-tenant query detected"
                )
        
        return ComplianceResult.allow(self.name)
