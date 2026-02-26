"""
Compliance module for Omnipath V2.

Provides a compliance-first architecture for agent tool execution,
adapted from Syntara-clean's proven patterns.

Components:
- ComplianceEngine: Evaluates actions against registered rules
- ComplianceRegistry: Plugin system for compliance rules
- ComplianceResult: Allow/Block decisions with reasoning
- ComplianceTrace: Audit trail of compliance checks
- ComplianceEvaluation: Complete evaluation result

Usage:
    from backend.agents.compliance import ComplianceEngine, ComplianceRegistry
    from backend.agents.compliance.rules import ToolPermissionRule
    
    # Register rules
    ComplianceRegistry.register(ToolPermissionRule)
    
    # Create engine
    engine = ComplianceEngine()
    
    # Evaluate action
    context = {"agent_type": "researcher", "tool_name": "web_search"}
    evaluation = engine.evaluate("web_search", context)
    
    if not evaluation.allowed:
        print(f"Blocked: {evaluation.reason}")
"""

from .models import (
    ComplianceResult,
    ComplianceTrace,
    ComplianceEvaluation
)

from .registry import (
    ComplianceRule,
    ComplianceRegistry
)

from .engine import ComplianceEngine

__all__ = [
    "ComplianceResult",
    "ComplianceTrace",
    "ComplianceEvaluation",
    "ComplianceRule",
    "ComplianceRegistry",
    "ComplianceEngine",
]
