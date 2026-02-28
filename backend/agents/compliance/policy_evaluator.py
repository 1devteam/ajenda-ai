"""
Policy Evaluation Engine - Real-time policy evaluation and enforcement.

Evaluates policies against execution context and enforces governance decisions.
Supports complex condition logic (AND/OR/NOT), caching, and conflict resolution.

Author: Dev Team Lead
Date: 2026-02-27
Built with Pride for Obex Blackvault
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.agents.compliance.policy_engine import (
    Policy,
    PolicyCondition,
    PolicyAction,
    PolicyStatus,
    ConditionType,
    ConditionOperator,
    ActionType,
    get_policy_manager,
)
from backend.agents.registry.asset_registry import AIAsset, get_registry
from backend.agents.compliance.risk_scoring import get_risk_scoring_engine


# ============================================================================
# Evaluation Context
# ============================================================================


@dataclass
class EvaluationContext:
    """Context for policy evaluation."""

    # Asset context
    asset: AIAsset
    operation: str  # "create", "update", "delete", "execute"

    # User context
    user_id: str
    user_role: str
    user_authority_level: int

    # Environmental context
    timestamp: datetime
    location: Optional[str] = None

    # Operational context
    data_accessed: List[str] = field(default_factory=list)
    api_endpoints: List[str] = field(default_factory=list)

    # Additional metadata
    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# Evaluation Result
# ============================================================================


@dataclass
class PolicyEvaluationResult:
    """Result of policy evaluation."""

    allowed: bool
    reason: str

    # Policies that were evaluated
    policies_evaluated: List[str] = field(default_factory=list)
    policies_matched: List[str] = field(default_factory=list)

    # Actions to take
    actions_required: List[PolicyAction] = field(default_factory=list)

    # Tags to add
    tags_to_add: List[str] = field(default_factory=list)

    # Alerts to send
    alerts_to_send: List[Dict[str, Any]] = field(default_factory=list)

    # Events to log
    events_to_log: List[Dict[str, Any]] = field(default_factory=list)

    # Approval requirements
    requires_approval: bool = False
    min_authority_level: Optional[int] = None
    approval_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "policies_evaluated": self.policies_evaluated,
            "policies_matched": self.policies_matched,
            "actions_required": [a.to_dict() for a in self.actions_required],
            "tags_to_add": self.tags_to_add,
            "alerts_to_send": self.alerts_to_send,
            "events_to_log": self.events_to_log,
            "requires_approval": self.requires_approval,
            "min_authority_level": self.min_authority_level,
            "approval_reason": self.approval_reason,
        }


# ============================================================================
# Policy Evaluator
# ============================================================================


class PolicyEvaluator:
    """Evaluates policies against execution context."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._policy_manager = get_policy_manager()
        self._registry = get_registry()
        self._risk_engine = get_risk_scoring_engine()

        # Evaluation cache (5-minute TTL)
        self._eval_cache: Dict[str, tuple[PolicyEvaluationResult, datetime]] = {}
        self._cache_ttl_seconds = 300

        self._initialized = True

    def evaluate(self, context: EvaluationContext) -> PolicyEvaluationResult:
        """Evaluate all applicable policies for the given context."""
        # Check cache
        cache_key = self._get_cache_key(context)
        if cache_key in self._eval_cache:
            result, cached_at = self._eval_cache[cache_key]
            if (datetime.utcnow() - cached_at).total_seconds() < self._cache_ttl_seconds:
                return result

        # Get applicable policies
        policies = self._policy_manager.list_policies(
            status=PolicyStatus.ACTIVE,
            applies_to=context.asset.asset_type.value,
        )

        result = PolicyEvaluationResult(
            allowed=True,
            reason="No policies deny this operation",
        )

        # Evaluate each policy
        for policy in policies:
            result.policies_evaluated.append(policy.policy_id)

            # Check if policy conditions are met
            if self._evaluate_conditions(policy.conditions, context):
                result.policies_matched.append(policy.policy_id)

                # Execute policy actions
                self._execute_actions(policy.actions, result)

                # Update policy enforcement stats
                policy.enforcement_count += 1
                policy.last_enforced_at = datetime.utcnow()

        # Cache result
        self._eval_cache[cache_key] = (result, datetime.utcnow())

        return result

    def _evaluate_conditions(
        self,
        conditions: List[PolicyCondition],
        context: EvaluationContext,
    ) -> bool:
        """Evaluate a list of conditions (implicitly AND)."""
        if not conditions:
            return True

        for condition in conditions:
            if not self._evaluate_condition(condition, context):
                return False

        return True

    def _evaluate_condition(
        self,
        condition: PolicyCondition,
        context: EvaluationContext,
    ) -> bool:
        """Evaluate a single condition."""
        # Evaluate NOT condition
        if condition.not_condition:
            return not self._evaluate_condition(condition.not_condition, context)

        # Evaluate OR conditions (main condition OR any of or_conditions)
        if condition.or_conditions:
            # Evaluate main condition
            actual_value = self._get_context_value(condition, context)
            expected_value = condition.value
            main_result = self._evaluate_operator(
                condition.operator,
                actual_value,
                expected_value,
            )

            # If main condition is true, return True (OR short-circuit)
            if main_result:
                return True

            # Otherwise check if any OR condition is true
            or_result = any(self._evaluate_condition(c, context) for c in condition.or_conditions)
            return or_result

        # Evaluate AND conditions (main condition AND all and_conditions)
        if condition.and_conditions:
            # Evaluate main condition first
            actual_value = self._get_context_value(condition, context)
            expected_value = condition.value
            main_result = self._evaluate_operator(
                condition.operator,
                actual_value,
                expected_value,
            )

            # If main condition is false, return False (AND short-circuit)
            if not main_result:
                return False

            # Otherwise check if all AND conditions are true
            and_result = all(self._evaluate_condition(c, context) for c in condition.and_conditions)
            return and_result

        # No AND/OR conditions, just evaluate the main condition
        actual_value = self._get_context_value(condition, context)
        expected_value = condition.value

        return self._evaluate_operator(
            condition.operator,
            actual_value,
            expected_value,
        )

    def _get_context_value(
        self,
        condition: PolicyCondition,
        context: EvaluationContext,
    ) -> Any:
        """Get the value from context based on condition type."""
        if condition.condition_type == ConditionType.ASSET_TYPE:
            return context.asset.asset_type.value

        elif condition.condition_type == ConditionType.ASSET_STATUS:
            return context.asset.status.value

        elif condition.condition_type == ConditionType.ASSET_TAG:
            return context.asset.tags

        elif condition.condition_type == ConditionType.ASSET_OWNER:
            return context.asset.owner

        elif condition.condition_type == ConditionType.RISK_SCORE:
            score = self._risk_engine.get_risk_score(context.asset.asset_id)
            return score.score if score else 0

        elif condition.condition_type == ConditionType.RISK_TIER:
            score = self._risk_engine.get_risk_score(context.asset.asset_id)
            return score.tier.value if score else "MINIMAL"

        elif condition.condition_type == ConditionType.USER_ROLE:
            return context.user_role

        elif condition.condition_type == ConditionType.USER_AUTHORITY:
            return context.user_authority_level

        elif condition.condition_type == ConditionType.TIME_OF_DAY:
            return context.timestamp.strftime("%H:%M")

        elif condition.condition_type == ConditionType.DAY_OF_WEEK:
            return context.timestamp.strftime("%A")

        elif condition.condition_type == ConditionType.LOCATION:
            return context.location

        elif condition.condition_type == ConditionType.DATA_ACCESSED:
            return context.data_accessed

        elif condition.condition_type == ConditionType.METADATA_FIELD:
            # Field is like "metadata.location" or just "location"
            if condition.field.startswith("metadata."):
                field_name = condition.field[9:]  # Remove "metadata."
                return context.asset.metadata.get(field_name)
            else:
                return context.asset.metadata.get(condition.field)

        return None

    def _evaluate_operator(
        self,
        operator: ConditionOperator,
        actual: Any,
        expected: Any,
    ) -> bool:
        """Evaluate an operator."""
        if operator == ConditionOperator.EQUALS:
            return actual == expected

        elif operator == ConditionOperator.NOT_EQUALS:
            return actual != expected

        elif operator == ConditionOperator.CONTAINS:
            if isinstance(actual, (list, tuple, set)):
                return expected in actual
            elif isinstance(actual, str):
                return expected in actual
            return False

        elif operator == ConditionOperator.NOT_CONTAINS:
            if isinstance(actual, (list, tuple, set)):
                return expected not in actual
            elif isinstance(actual, str):
                return expected not in actual
            return True

        elif operator == ConditionOperator.IN:
            if isinstance(expected, (list, tuple, set)):
                return actual in expected
            return False

        elif operator == ConditionOperator.NOT_IN:
            if isinstance(expected, (list, tuple, set)):
                return actual not in expected
            return True

        elif operator == ConditionOperator.GREATER_THAN:
            try:
                return float(actual) > float(expected)
            except (ValueError, TypeError):
                return False

        elif operator == ConditionOperator.LESS_THAN:
            try:
                return float(actual) < float(expected)
            except (ValueError, TypeError):
                return False

        elif operator == ConditionOperator.GREATER_EQUAL:
            try:
                return float(actual) >= float(expected)
            except (ValueError, TypeError):
                return False

        elif operator == ConditionOperator.LESS_EQUAL:
            try:
                return float(actual) <= float(expected)
            except (ValueError, TypeError):
                return False

        elif operator == ConditionOperator.BETWEEN:
            if isinstance(expected, (list, tuple)) and len(expected) == 2:
                try:
                    val = float(actual) if isinstance(actual, (int, float)) else actual
                    return expected[0] <= val <= expected[1]
                except (ValueError, TypeError):
                    # For time comparison
                    if isinstance(actual, str) and all(isinstance(e, str) for e in expected):
                        return expected[0] <= actual <= expected[1]
                    return False
            return False

        elif operator == ConditionOperator.NOT_BETWEEN:
            if isinstance(expected, (list, tuple)) and len(expected) == 2:
                try:
                    val = float(actual) if isinstance(actual, (int, float)) else actual
                    return not (expected[0] <= val <= expected[1])
                except (ValueError, TypeError):
                    # For time comparison
                    if isinstance(actual, str) and all(isinstance(e, str) for e in expected):
                        return not (expected[0] <= actual <= expected[1])
                    return True
            return True

        return False

    def _execute_actions(
        self,
        actions: List[PolicyAction],
        result: PolicyEvaluationResult,
    ) -> None:
        """Execute policy actions and update result."""
        for action in actions:
            result.actions_required.append(action)

            if action.action_type == ActionType.DENY:
                result.allowed = False
                result.reason = action.parameters.get(
                    "reason",
                    "Operation denied by policy",
                )

            elif action.action_type == ActionType.REQUIRE_APPROVAL:
                result.requires_approval = True
                result.min_authority_level = action.parameters.get(
                    "min_authority_level",
                    3,
                )
                result.approval_reason = action.parameters.get(
                    "reason",
                    "Approval required by policy",
                )

            elif action.action_type == ActionType.ADD_TAG:
                tags = action.parameters.get("tags", [])
                result.tags_to_add.extend(tags)

            elif action.action_type == ActionType.SEND_ALERT:
                result.alerts_to_send.append(
                    {
                        "recipients": action.parameters.get("recipients", []),
                        "message": action.parameters.get("message", "Policy alert"),
                        "severity": action.parameters.get("severity", "info"),
                    }
                )

            elif action.action_type == ActionType.LOG_EVENT:
                result.events_to_log.append(
                    {
                        "event_type": action.parameters.get("event_type", "policy_event"),
                        "severity": action.parameters.get("severity", "info"),
                        "details": action.parameters.get("details", {}),
                    }
                )

    def get_applicable_policies(
        self,
        asset_type: Optional[str] = None,
    ) -> List[Policy]:
        """Get all applicable policies for an asset type."""
        return self._policy_manager.list_policies(
            status=PolicyStatus.ACTIVE,
            applies_to=asset_type,
        )

    def test_policy(
        self,
        policy: Policy,
        context: EvaluationContext,
    ) -> PolicyEvaluationResult:
        """Test a policy without activating it."""
        result = PolicyEvaluationResult(
            allowed=True,
            reason="Test mode",
        )

        if self._evaluate_conditions(policy.conditions, context):
            result.policies_matched.append(policy.policy_id)
            self._execute_actions(policy.actions, result)

        return result

    def _get_cache_key(self, context: EvaluationContext) -> str:
        """Generate cache key for evaluation context."""
        return f"{context.asset.asset_id}:{context.operation}:{context.user_id}"

    def clear_cache(self) -> None:
        """Clear evaluation cache."""
        self._eval_cache.clear()


def get_policy_evaluator() -> PolicyEvaluator:
    """Get the singleton PolicyEvaluator instance."""
    return PolicyEvaluator()
