"""
Compliance engine for Omnipath V2.

Evaluates actions against registered compliance rules.
Adapted from Syntara-clean's ComplianceEngine pattern.
"""

from typing import Dict, Any, List
from .models import ComplianceResult, ComplianceTrace, ComplianceEvaluation
from .registry import ComplianceRegistry


class ComplianceEngine:
    """
    Runs all registered compliance rules in order and accumulates traces.
    
    The engine evaluates actions against all registered rules,
    stopping at the first rule that blocks the action.
    
    Usage:
        # Create engine with default rules
        engine = ComplianceEngine()
        
        # Evaluate action
        context = {
            "agent_type": "researcher",
            "tool_name": "web_search",
            "parameters": {"query": "test"}
        }
        evaluation = engine.evaluate("web_search", context)
        
        if not evaluation.allowed:
            print(f"Blocked: {evaluation.reason}")
    
    Example:
        from backend.agents.compliance import ComplianceEngine, ComplianceRegistry
        from backend.agents.compliance.rules import ToolPermissionRule
        
        # Register rules
        ComplianceRegistry.register(ToolPermissionRule)
        
        # Create engine
        engine = ComplianceEngine(auto_register_defaults=False)
        
        # Evaluate
        evaluation = engine.evaluate("web_search", {
            "agent_type": "researcher",
            "tool_name": "web_search"
        })
    """
    
    def __init__(self, auto_register_defaults: bool = True) -> None:
        """
        Initialize compliance engine.
        
        Args:
            auto_register_defaults: If True, automatically register default rules
                                   if no rules are registered yet
        
        Example:
            # With default rules
            engine = ComplianceEngine()
            
            # Without default rules (for testing)
            engine = ComplianceEngine(auto_register_defaults=False)
        """
        # Auto-register default rules if nothing registered yet
        if auto_register_defaults and ComplianceRegistry.count() == 0:
            from .rules import ToolPermissionRule, DataAccessRule, RateLimitRule
            
            ComplianceRegistry.register(ToolPermissionRule)
            ComplianceRegistry.register(DataAccessRule)
            ComplianceRegistry.register(RateLimitRule)
    
    def evaluate(self, action: str, context: Dict[str, Any]) -> ComplianceEvaluation:
        """
        Evaluate action against all registered compliance rules.
        
        Rules are evaluated in registration order. The first rule that
        blocks the action stops evaluation and returns a blocked result.
        
        Args:
            action: Name of the action being evaluated (typically tool name)
            context: Dictionary containing:
                - agent_id: str - Unique agent identifier
                - agent_type: str - Type of agent (researcher, analyst, developer)
                - tenant_id: str - Tenant identifier
                - tool_name: str - Name of the tool being executed
                - parameters: Dict - Tool parameters
                - mission_payload: Dict - Agent mission payload
        
        Returns:
            ComplianceEvaluation with:
                - allowed: bool - Whether action is allowed
                - reason: str - Explanation if blocked
                - traces: List[ComplianceTrace] - Audit trail of all checks
        
        Example:
            context = {
                "agent_id": "agent_123",
                "agent_type": "researcher",
                "tenant_id": "tenant_456",
                "tool_name": "web_search",
                "parameters": {"query": "test"},
                "mission_payload": {"task": "research"}
            }
            
            evaluation = engine.evaluate("web_search", context)
            
            if not evaluation.allowed:
                print(f"Blocked by: {evaluation.blocked_by}")
                print(f"Reason: {evaluation.reason}")
            else:
                print(f"Passed {len(evaluation.traces)} rules")
        """
        traces: List[ComplianceTrace] = []
        
        # Get all registered rules
        rules = ComplianceRegistry.get_rules()
        
        # Evaluate each rule
        for rule_cls in rules:
            rule = rule_cls()
            result = rule.check(context)
            
            # Add trace
            traces.append(
                ComplianceTrace(
                    rule=result.rule,
                    allowed=result.allowed,
                    reason=result.reason,
                )
            )
            
            # Stop at first blocking rule
            if not result.allowed:
                return ComplianceEvaluation(
                    allowed=False,
                    reason=result.reason,
                    traces=traces,
                )
        
        # All rules passed
        return ComplianceEvaluation(
            allowed=True,
            reason="",
            traces=traces,
        )
