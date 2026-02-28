"""
Compliance data models for Omnipath V2.

Adapted from Syntara-clean's compliance architecture.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List
from datetime import datetime


@dataclass
class ComplianceResult:
    """
    Result of a single compliance rule check.

    Attributes:
        allowed: Whether the action is allowed
        reason: Explanation if blocked (empty if allowed)
        rule: Name of the rule that produced this result

    Example:
        # Allow result
        result = ComplianceResult.allow("tool_permission")

        # Block result
        result = ComplianceResult.block(
            rule="tool_permission",
            reason="Agent 'researcher' not permitted to use 'file_writer'"
        )
    """

    allowed: bool
    reason: str
    rule: str

    @staticmethod
    def allow(rule: str) -> "ComplianceResult":
        """Create an allow result."""
        return ComplianceResult(allowed=True, reason="", rule=rule)

    @staticmethod
    def block(rule: str, reason: str) -> "ComplianceResult":
        """Create a block result with reason."""
        return ComplianceResult(allowed=False, reason=reason, rule=rule)


@dataclass
class ComplianceTrace:
    """
    Audit trail entry for a single rule check.

    Attributes:
        rule: Name of the rule
        allowed: Whether the rule allowed the action
        reason: Explanation (populated if blocked)
        timestamp: When the check occurred

    Example:
        trace = ComplianceTrace(
            rule="tool_permission",
            allowed=True,
            reason=""
        )
    """

    rule: str
    allowed: bool
    reason: str
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "rule": self.rule,
            "allowed": self.allowed,
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class ComplianceEvaluation:
    """
    Complete evaluation result from compliance engine.

    Attributes:
        allowed: Whether the action is allowed overall
        reason: Explanation if blocked (empty if allowed)
        traces: List of all rule checks performed
        timestamp: When the evaluation occurred

    Example:
        evaluation = engine.evaluate("web_search", context)

        if not evaluation.allowed:
            print(f"Blocked by: {evaluation.blocked_by}")
            print(f"Reason: {evaluation.reason}")
        else:
            print(f"Passed rules: {evaluation.passed_rules}")
    """

    allowed: bool
    reason: str
    traces: List[ComplianceTrace]
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "traces": [trace.to_dict() for trace in self.traces],
            "timestamp": self.timestamp.isoformat(),
        }

    @property
    def blocked_by(self) -> List[str]:
        """Get list of rules that blocked the action."""
        return [trace.rule for trace in self.traces if not trace.allowed]

    @property
    def passed_rules(self) -> List[str]:
        """Get list of rules that allowed the action."""
        return [trace.rule for trace in self.traces if trace.allowed]
