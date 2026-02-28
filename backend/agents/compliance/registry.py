"""
Compliance rule registry for Omnipath V2.

Provides a pluggable system for registering and managing compliance rules.
Adapted from Syntara-clean's ComplianceRegistry pattern.
"""

from typing import List, Type, Protocol, Dict, Any
from .models import ComplianceResult


class ComplianceRule(Protocol):
    """
    Protocol for compliance rules.

    All compliance rules must implement:
    - name: str - Unique identifier for the rule
    - description: str - Human-readable description
    - check(context: Dict) -> ComplianceResult - Evaluation logic

    Example:
        class MyRule:
            name = "my_rule"
            description = "My custom compliance rule"

            def check(self, context: Dict) -> ComplianceResult:
                if context.get("some_condition"):
                    return ComplianceResult.allow(self.name)
                return ComplianceResult.block(
                    rule=self.name,
                    reason="Condition not met"
                )
    """

    name: str
    description: str

    def check(self, context: Dict[str, Any]) -> ComplianceResult:
        """
        Evaluate the rule against the given context.

        Args:
            context: Dictionary containing:
                - agent_id: str
                - agent_type: str
                - tenant_id: str
                - tool_name: str
                - parameters: Dict
                - mission_payload: Dict

        Returns:
            ComplianceResult indicating allow or block
        """
        ...  # pragma: no cover - protocol


class ComplianceRegistry:
    """
    Global registry for compliance rules.

    Provides a centralized system for registering, retrieving,
    and managing compliance rules.

    Usage:
        # Register a rule
        ComplianceRegistry.register(MyRule)

        # Get all rules
        rules = ComplianceRegistry.get_rules()

        # Clear all rules (testing)
        ComplianceRegistry.clear()

    Example:
        from backend.agents.compliance import ComplianceRegistry
        from backend.agents.compliance.rules import ToolPermissionRule

        # Register default rules
        ComplianceRegistry.register(ToolPermissionRule)

        # Check registration
        print(f"Rules registered: {ComplianceRegistry.count()}")
    """

    _rules: List[Type[ComplianceRule]] = []

    @classmethod
    def register(cls, rule_cls: Type[ComplianceRule]) -> None:
        """
        Register a compliance rule.

        Args:
            rule_cls: Class implementing ComplianceRule protocol

        Example:
            ComplianceRegistry.register(ToolPermissionRule)
        """
        if rule_cls not in cls._rules:
            cls._rules.append(rule_cls)

    @classmethod
    def get_rules(cls) -> List[Type[ComplianceRule]]:
        """
        Get all registered compliance rules.

        Returns:
            List of rule classes

        Example:
            rules = ComplianceRegistry.get_rules()
            for rule_cls in rules:
                print(f"Rule: {rule_cls.name}")
        """
        return list(cls._rules)

    @classmethod
    def clear(cls) -> None:
        """
        Clear all registered rules.

        Primarily used for testing.

        Example:
            # In test setup
            ComplianceRegistry.clear()
        """
        cls._rules.clear()

    @classmethod
    def get_rule_by_name(cls, name: str) -> Type[ComplianceRule] | None:
        """
        Get a specific rule by name.

        Args:
            name: Name of the rule

        Returns:
            Rule class if found, None otherwise

        Example:
            rule_cls = ComplianceRegistry.get_rule_by_name("tool_permission")
            if rule_cls:
                print(f"Found: {rule_cls.description}")
        """
        for rule_cls in cls._rules:
            if rule_cls.name == name:
                return rule_cls
        return None

    @classmethod
    def is_registered(cls, rule_cls: Type[ComplianceRule]) -> bool:
        """
        Check if a rule is registered.

        Args:
            rule_cls: Rule class to check

        Returns:
            True if registered, False otherwise

        Example:
            if ComplianceRegistry.is_registered(ToolPermissionRule):
                print("Rule already registered")
        """
        return rule_cls in cls._rules

    @classmethod
    def count(cls) -> int:
        """
        Get count of registered rules.

        Returns:
            Number of registered rules

        Example:
            print(f"Total rules: {ComplianceRegistry.count()}")
        """
        return len(cls._rules)
