"""
Policy Engine - Custom Governance Policy System.

Enables organizations to define, manage, and enforce custom governance policies
beyond built-in rules. Provides declarative policy language with templates,
inheritance, and real-time evaluation.

Author: Dev Team Lead
Date: 2026-02-27
Built with Pride for Obex Blackvault
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


# ============================================================================
# Enums
# ============================================================================


class PolicyStatus(Enum):
    """Policy lifecycle status."""

    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class ConditionType(Enum):
    """Types of conditions that can be evaluated."""

    ASSET_TYPE = "asset_type"
    ASSET_STATUS = "asset_status"
    ASSET_TAG = "asset_tag"
    ASSET_OWNER = "asset_owner"
    RISK_SCORE = "risk_score"
    RISK_TIER = "risk_tier"
    USER_ROLE = "user_role"
    USER_AUTHORITY = "user_authority"
    TIME_OF_DAY = "time_of_day"
    DAY_OF_WEEK = "day_of_week"
    LOCATION = "location"
    DATA_ACCESSED = "data_accessed"
    METADATA_FIELD = "metadata_field"


class ConditionOperator(Enum):
    """Operators for condition evaluation."""

    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    IN = "in"
    NOT_IN = "not_in"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    GREATER_EQUAL = "greater_equal"
    LESS_EQUAL = "less_equal"
    BETWEEN = "between"
    NOT_BETWEEN = "not_between"


class ActionType(Enum):
    """Actions that can be taken when policy conditions are met."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"
    ADD_TAG = "add_tag"
    SEND_ALERT = "send_alert"
    LOG_EVENT = "log_event"
    ESCALATE = "escalate"


# ============================================================================
# Data Models
# ============================================================================


@dataclass
class PolicyCondition:
    """Condition that must be met for policy to apply."""

    condition_type: ConditionType
    operator: ConditionOperator
    field: str
    value: Any

    # Logical operators
    and_conditions: List["PolicyCondition"] = field(default_factory=list)
    or_conditions: List["PolicyCondition"] = field(default_factory=list)
    not_condition: Optional["PolicyCondition"] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "condition_type": self.condition_type.value,
            "operator": self.operator.value,
            "field": self.field,
            "value": self.value,
            "and_conditions": [c.to_dict() for c in self.and_conditions],
            "or_conditions": [c.to_dict() for c in self.or_conditions],
            "not_condition": (self.not_condition.to_dict() if self.not_condition else None),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PolicyCondition":
        """Create from dictionary."""
        return cls(
            condition_type=ConditionType(data["condition_type"]),
            operator=ConditionOperator(data["operator"]),
            field=data["field"],
            value=data["value"],
            and_conditions=[cls.from_dict(c) for c in data.get("and_conditions", [])],
            or_conditions=[cls.from_dict(c) for c in data.get("or_conditions", [])],
            not_condition=(
                cls.from_dict(data["not_condition"]) if data.get("not_condition") else None
            ),
        )


@dataclass
class PolicyAction:
    """Action to take when policy conditions are met."""

    action_type: ActionType
    parameters: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "action_type": self.action_type.value,
            "parameters": self.parameters,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PolicyAction":
        """Create from dictionary."""
        return cls(
            action_type=ActionType(data["action_type"]),
            parameters=data.get("parameters", {}),
        )


@dataclass
class Policy:
    """Governance policy definition."""

    policy_id: str
    name: str
    description: str
    status: PolicyStatus

    # Policy logic
    conditions: List[PolicyCondition]
    actions: List[PolicyAction]

    # Audit fields — optional with sensible defaults so callers don't need
    # to specify them for simple inline/test policy creation.
    version: str = "1.0"
    created_at: datetime = field(default_factory=datetime.utcnow)
    created_by: str = "system"
    updated_at: datetime = field(default_factory=datetime.utcnow)
    updated_by: str = "system"

    # Arbitrary key-value metadata (e.g. template_id, tags, custom attributes).
    # Used by the compliance checker to match required policy templates.
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Inheritance
    parent_policy_id: Optional[str] = None
    override_parent: bool = False

    # Scope
    applies_to: List[str] = field(default_factory=list)  # Asset types, empty = all
    priority: int = 0  # Higher priority evaluated first

    # Audit
    enforcement_count: int = 0
    last_enforced_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "policy_id": self.policy_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "status": self.status.value,
            "conditions": [c.to_dict() for c in self.conditions],
            "actions": [a.to_dict() for a in self.actions],
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "updated_at": self.updated_at.isoformat(),
            "updated_by": self.updated_by,
            "metadata": self.metadata,
            "parent_policy_id": self.parent_policy_id,
            "override_parent": self.override_parent,
            "applies_to": self.applies_to,
            "priority": self.priority,
            "enforcement_count": self.enforcement_count,
            "last_enforced_at": (
                self.last_enforced_at.isoformat() if self.last_enforced_at else None
            ),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Policy":
        """Create from dictionary."""
        return cls(
            policy_id=data["policy_id"],
            name=data["name"],
            description=data["description"],
            version=data.get("version", "1.0"),
            status=PolicyStatus(data["status"]),
            conditions=[PolicyCondition.from_dict(c) for c in data["conditions"]],
            actions=[PolicyAction.from_dict(a) for a in data["actions"]],
            created_at=(
                datetime.fromisoformat(data["created_at"])
                if data.get("created_at")
                else datetime.utcnow()
            ),
            created_by=data.get("created_by", "system"),
            updated_at=(
                datetime.fromisoformat(data["updated_at"])
                if data.get("updated_at")
                else datetime.utcnow()
            ),
            updated_by=data.get("updated_by", "system"),
            metadata=data.get("metadata", {}),
            parent_policy_id=data.get("parent_policy_id"),
            override_parent=data.get("override_parent", False),
            applies_to=data.get("applies_to", []),
            priority=data.get("priority", 0),
            enforcement_count=data.get("enforcement_count", 0),
            last_enforced_at=(
                datetime.fromisoformat(data["last_enforced_at"])
                if data.get("last_enforced_at")
                else None
            ),
        )


@dataclass
class PolicyTemplate:
    """Template for creating policies."""

    template_id: str
    name: str
    description: str
    category: str  # "data_protection", "risk_management", "operational", "compliance"

    # Template definition
    conditions: List[PolicyCondition]
    actions: List[PolicyAction]

    # Metadata
    created_at: datetime
    created_by: str

    # Usage
    usage_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "template_id": self.template_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "conditions": [c.to_dict() for c in self.conditions],
            "actions": [a.to_dict() for a in self.actions],
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "usage_count": self.usage_count,
        }

    def instantiate(self, name: str, created_by: str, **overrides) -> Policy:
        """Create a policy from this template."""
        now = datetime.utcnow()

        policy = Policy(
            policy_id=f"policy-{uuid.uuid4().hex[:12]}",
            name=name,
            description=overrides.get("description", self.description),
            version="1.0",
            status=PolicyStatus.DRAFT,
            conditions=self.conditions.copy(),
            actions=self.actions.copy(),
            created_at=now,
            created_by=created_by,
            updated_at=now,
            updated_by=created_by,
            applies_to=overrides.get("applies_to", []),
            priority=overrides.get("priority", 0),
        )

        self.usage_count += 1

        return policy


# ============================================================================
# Policy Template Library
# ============================================================================


class PolicyTemplateLibrary:
    """Library of pre-built policy templates."""

    @staticmethod
    def get_gdpr_pii_protection() -> PolicyTemplate:
        """GDPR PII protection template."""
        return PolicyTemplate(
            template_id="tmpl-gdpr-pii",
            name="GDPR PII Protection",
            description="Enforce GDPR requirements for PII handling",
            category="data_protection",
            conditions=[
                PolicyCondition(
                    condition_type=ConditionType.ASSET_TAG,
                    operator=ConditionOperator.CONTAINS,
                    field="tags",
                    value="pii",
                )
            ],
            actions=[
                PolicyAction(
                    action_type=ActionType.REQUIRE_APPROVAL,
                    parameters={
                        "min_authority_level": 3,
                        "reason": "GDPR: PII processing requires approval",
                    },
                ),
                PolicyAction(
                    action_type=ActionType.ADD_TAG,
                    parameters={"tags": ["gdpr", "requires-dpia"]},
                ),
                PolicyAction(
                    action_type=ActionType.LOG_EVENT,
                    parameters={
                        "event_type": "gdpr_pii_access",
                        "severity": "high",
                    },
                ),
            ],
            created_at=datetime.utcnow(),
            created_by="system",
        )

    @staticmethod
    def get_hipaa_phi_protection() -> PolicyTemplate:
        """HIPAA PHI protection template."""
        return PolicyTemplate(
            template_id="tmpl-hipaa-phi",
            name="HIPAA PHI Protection",
            description="Enforce HIPAA requirements for PHI handling",
            category="data_protection",
            conditions=[
                PolicyCondition(
                    condition_type=ConditionType.ASSET_TAG,
                    operator=ConditionOperator.CONTAINS,
                    field="tags",
                    value="phi",
                )
            ],
            actions=[
                PolicyAction(
                    action_type=ActionType.REQUIRE_APPROVAL,
                    parameters={
                        "min_authority_level": 4,
                        "reason": "HIPAA: PHI access requires Compliance Officer approval",
                    },
                ),
                PolicyAction(
                    action_type=ActionType.ADD_TAG,
                    parameters={"tags": ["hipaa", "healthcare"]},
                ),
                PolicyAction(
                    action_type=ActionType.LOG_EVENT,
                    parameters={
                        "event_type": "hipaa_phi_access",
                        "severity": "critical",
                    },
                ),
            ],
            created_at=datetime.utcnow(),
            created_by="system",
        )

    @staticmethod
    def get_production_deployment_gate() -> PolicyTemplate:
        """Production deployment approval template."""
        return PolicyTemplate(
            template_id="tmpl-prod-gate",
            name="Production Deployment Gate",
            description="Require approval for production deployments",
            category="operational",
            conditions=[
                PolicyCondition(
                    condition_type=ConditionType.METADATA_FIELD,
                    operator=ConditionOperator.EQUALS,
                    field="location",
                    value="production",
                )
            ],
            actions=[
                PolicyAction(
                    action_type=ActionType.REQUIRE_APPROVAL,
                    parameters={
                        "min_authority_level": 3,
                        "reason": "Production deployment requires Admin approval",
                    },
                ),
            ],
            created_at=datetime.utcnow(),
            created_by="system",
        )

    @staticmethod
    def get_high_risk_approval() -> PolicyTemplate:
        """High-risk asset approval template."""
        return PolicyTemplate(
            template_id="tmpl-high-risk",
            name="High-Risk Asset Approval",
            description="Require approval for high-risk assets",
            category="risk_management",
            conditions=[
                PolicyCondition(
                    condition_type=ConditionType.RISK_TIER,
                    operator=ConditionOperator.IN,
                    field="risk_tier",
                    value=["HIGH", "CRITICAL"],
                )
            ],
            actions=[
                PolicyAction(
                    action_type=ActionType.REQUIRE_APPROVAL,
                    parameters={
                        "min_authority_level": 3,
                        "reason": "High-risk assets require Admin approval",
                    },
                ),
                PolicyAction(
                    action_type=ActionType.SEND_ALERT,
                    parameters={
                        "recipients": ["compliance-team"],
                        "message": "High-risk asset requires review",
                    },
                ),
            ],
            created_at=datetime.utcnow(),
            created_by="system",
        )

    @staticmethod
    def get_business_hours_restriction() -> PolicyTemplate:
        """Business hours restriction template."""
        return PolicyTemplate(
            template_id="tmpl-business-hours",
            name="Business Hours Restriction",
            description="Restrict high-risk operations to business hours",
            category="operational",
            conditions=[
                PolicyCondition(
                    condition_type=ConditionType.RISK_TIER,
                    operator=ConditionOperator.IN,
                    field="risk_tier",
                    value=["HIGH", "CRITICAL"],
                    and_conditions=[
                        PolicyCondition(
                            condition_type=ConditionType.TIME_OF_DAY,
                            operator=ConditionOperator.NOT_BETWEEN,
                            field="time",
                            value=["09:00", "17:00"],
                        )
                    ],
                )
            ],
            actions=[
                PolicyAction(
                    action_type=ActionType.DENY,
                    parameters={
                        "reason": "High-risk operations only allowed during business hours (9am-5pm)",  # noqa: E501
                    },
                ),
            ],
            created_at=datetime.utcnow(),
            created_by="system",
        )

    @staticmethod
    def get_all_templates() -> List[PolicyTemplate]:
        """Get all built-in templates."""
        return [
            PolicyTemplateLibrary.get_gdpr_pii_protection(),
            PolicyTemplateLibrary.get_hipaa_phi_protection(),
            PolicyTemplateLibrary.get_production_deployment_gate(),
            PolicyTemplateLibrary.get_high_risk_approval(),
            PolicyTemplateLibrary.get_business_hours_restriction(),
        ]


# ============================================================================
# Policy Manager
# ============================================================================


class PolicyManager:
    """Manages policy lifecycle and storage."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._policies: Dict[str, Policy] = {}
        self._templates: Dict[str, PolicyTemplate] = {}
        self._policy_history: Dict[str, List[Dict[str, Any]]] = {}

        # Load built-in templates
        for template in PolicyTemplateLibrary.get_all_templates():
            self._templates[template.template_id] = template

        self._initialized = True

    def create_policy(self, policy: Policy) -> Policy:
        """Create a new policy."""
        if policy.policy_id in self._policies:
            raise ValueError(f"Policy {policy.policy_id} already exists")

        self._policies[policy.policy_id] = policy
        self._record_history(policy.policy_id, "created", policy.created_by)

        return policy

    def get_policy(self, policy_id: str) -> Optional[Policy]:
        """Get policy by ID."""
        return self._policies.get(policy_id)

    def list_policies(
        self,
        status: Optional[PolicyStatus] = None,
        applies_to: Optional[str] = None,
    ) -> List[Policy]:
        """List policies with optional filters."""
        policies = list(self._policies.values())

        if status:
            policies = [p for p in policies if p.status == status]

        if applies_to:
            policies = [p for p in policies if not p.applies_to or applies_to in p.applies_to]

        # Sort by priority (highest first)
        policies.sort(key=lambda p: p.priority, reverse=True)

        return policies

    def update_policy(self, policy_id: str, updated_by: str, **updates) -> Policy:
        """Update an existing policy."""
        policy = self.get_policy(policy_id)
        if not policy:
            raise ValueError(f"Policy {policy_id} not found")

        # Update fields
        for key, value in updates.items():
            if hasattr(policy, key):
                setattr(policy, key, value)

        policy.updated_at = datetime.utcnow()
        policy.updated_by = updated_by
        policy.version = f"{float(policy.version) + 0.1:.1f}"

        self._record_history(policy_id, "updated", updated_by, updates)

        return policy

    def delete_policy(self, policy_id: str, deleted_by: str) -> None:
        """Delete a policy."""
        if policy_id not in self._policies:
            raise ValueError(f"Policy {policy_id} not found")

        del self._policies[policy_id]
        self._record_history(policy_id, "deleted", deleted_by)

    def activate_policy(self, policy_id: str, activated_by: str) -> Policy:
        """Activate a policy."""
        return self.update_policy(policy_id, activated_by, status=PolicyStatus.ACTIVE)

    def deactivate_policy(self, policy_id: str, deactivated_by: str) -> Policy:
        """Deactivate a policy."""
        return self.update_policy(policy_id, deactivated_by, status=PolicyStatus.DEPRECATED)

    def get_policy_history(self, policy_id: str) -> List[Dict[str, Any]]:
        """Get change history for a policy."""
        return self._policy_history.get(policy_id, [])

    def _record_history(
        self,
        policy_id: str,
        action: str,
        user: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a change in policy history."""
        if policy_id not in self._policy_history:
            self._policy_history[policy_id] = []

        self._policy_history[policy_id].append(
            {
                "timestamp": datetime.utcnow().isoformat(),
                "action": action,
                "user": user,
                "details": details or {},
            }
        )

    # Template methods

    def get_template(self, template_id: str) -> Optional[PolicyTemplate]:
        """Get template by ID."""
        return self._templates.get(template_id)

    def list_templates(self, category: Optional[str] = None) -> List[PolicyTemplate]:
        """List templates with optional category filter."""
        templates = list(self._templates.values())

        if category:
            templates = [t for t in templates if t.category == category]

        return templates

    def create_from_template(
        self,
        template_id: str,
        name: str,
        created_by: str,
        **overrides,
    ) -> Policy:
        """Create a policy from a template."""
        template = self.get_template(template_id)
        if not template:
            raise ValueError(f"Template {template_id} not found")

        policy = template.instantiate(name, created_by, **overrides)
        return self.create_policy(policy)

    def create_template(self, template: PolicyTemplate) -> PolicyTemplate:
        """Create a custom template."""
        if template.template_id in self._templates:
            raise ValueError(f"Template {template.template_id} already exists")

        self._templates[template.template_id] = template
        return template

    def clear(self) -> None:
        """Clear all policies (for testing)."""
        self._policies.clear()
        self._policy_history.clear()
        # Don't clear templates - they're built-in


def get_policy_manager() -> PolicyManager:
    """Get the singleton PolicyManager instance."""
    return PolicyManager()
