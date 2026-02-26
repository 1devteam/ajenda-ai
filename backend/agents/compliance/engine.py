"""
Compliance engine for Omnipath V2.

Evaluates actions against registered compliance rules.
Adapted from Syntara-clean's ComplianceEngine pattern.
"""

from typing import Dict, Any, List
import time

from .models import ComplianceResult, ComplianceTrace, ComplianceEvaluation
from .registry import ComplianceRegistry
from backend.integrations.observability.prometheus_metrics import get_metrics

try:
    from opentelemetry import trace
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False


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
        
        # Initialize metrics
        self.metrics = get_metrics()
        
        # Initialize tracer
        if OTEL_AVAILABLE:
            self.tracer = trace.get_tracer(__name__)
        else:
            self.tracer = None
    
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
        # Start span for compliance check
        if self.tracer:
            with self.tracer.start_as_current_span(
                "compliance.evaluate",
                attributes={
                    "compliance.action": action,
                    "compliance.agent_type": context.get("agent_type", "unknown"),
                    "compliance.tool_name": action,
                    "compliance.agent_id": context.get("agent_id", "unknown"),
                }
            ) as span:
                return self._evaluate_with_span(action, context, span)
        else:
            return self._evaluate_with_span(action, context, None)
    
    def _evaluate_with_span(
        self,
        action: str,
        context: Dict[str, Any],
        span
    ) -> ComplianceEvaluation:
        """Internal evaluation with optional span."""
        start_time = time.time()
        traces: List[ComplianceTrace] = []
        
        # Get all registered rules
        rules = ComplianceRegistry.get_rules()
        
        # Add rule count to span
        if span:
            span.set_attribute("compliance.rules_count", len(rules))
        
        # Evaluate each rule
        for rule_cls in rules:
            rule = rule_cls()
            result = rule.check(context)
            
            # Record rule evaluation metric
            self.metrics.record_compliance_rule_evaluation(
                rule_name=result.rule,
                passed=result.allowed
            )
            
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
                # Record block metric
                self.metrics.record_compliance_block(
                    agent_type=context.get("agent_type", "unknown"),
                    tool_name=action,
                    rule_name=result.rule
                )
                
                # Record overall check metric
                duration = time.time() - start_time
                self.metrics.record_compliance_check(
                    agent_type=context.get("agent_type", "unknown"),
                    tool_name=action,
                    allowed=False,
                    duration_seconds=duration
                )
                
                # Add span attributes for blocked action
                if span:
                    span.set_attribute("compliance.result", "blocked")
                    span.set_attribute("compliance.blocked_by", result.rule)
                    span.set_attribute("compliance.reason", result.reason)
                    span.set_attribute("compliance.duration_ms", duration * 1000)
                
                return ComplianceEvaluation(
                    allowed=False,
                    reason=result.reason,
                    traces=traces,
                )
        
        # All rules passed - record success metric
        duration = time.time() - start_time
        self.metrics.record_compliance_check(
            agent_type=context.get("agent_type", "unknown"),
            tool_name=action,
            allowed=True,
            duration_seconds=duration
        )
        
        # Add span attributes for allowed action
        if span:
            span.set_attribute("compliance.result", "allowed")
            span.set_attribute("compliance.rules_passed", len(traces))
            span.set_attribute("compliance.duration_ms", duration * 1000)
        
        return ComplianceEvaluation(
            allowed=True,
            reason="",
            traces=traces,
        )
