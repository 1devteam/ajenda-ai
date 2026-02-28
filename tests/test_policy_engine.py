"""
Tests for Policy Engine.

Author: Dev Team Lead
Date: 2026-02-27
Built with Pride for Obex Blackvault
"""

import pytest
from datetime import datetime
import uuid

from backend.agents.compliance.policy_engine import (
    Policy,
    PolicyCondition,
    PolicyAction,
    PolicyTemplate,
    PolicyStatus,
    ConditionType,
    ConditionOperator,
    ActionType,
    PolicyTemplateLibrary,
    get_policy_manager,
)

pytestmark = pytest.mark.unit


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def clear_manager():
    """Clear policy manager before each test."""
    manager = get_policy_manager()
    manager.clear()
    yield
    manager.clear()


@pytest.fixture
def sample_condition():
    """Create a sample policy condition."""
    return PolicyCondition(
        condition_type=ConditionType.ASSET_TAG,
        operator=ConditionOperator.CONTAINS,
        field="tags",
        value="pii",
    )


@pytest.fixture
def sample_action():
    """Create a sample policy action."""
    return PolicyAction(
        action_type=ActionType.REQUIRE_APPROVAL,
        parameters={"min_authority_level": 3},
    )


@pytest.fixture
def sample_policy(sample_condition, sample_action):
    """Create a sample policy."""
    now = datetime.utcnow()
    return Policy(
        policy_id=f"policy-{uuid.uuid4().hex[:12]}",
        name="Test Policy",
        description="A test policy",
        version="1.0",
        status=PolicyStatus.DRAFT,
        conditions=[sample_condition],
        actions=[sample_action],
        created_at=now,
        created_by="test-user",
        updated_at=now,
        updated_by="test-user",
    )


# ============================================================================
# PolicyCondition Tests
# ============================================================================


def test_condition_creation(sample_condition):
    """Test creating a policy condition."""
    assert sample_condition.condition_type == ConditionType.ASSET_TAG
    assert sample_condition.operator == ConditionOperator.CONTAINS
    assert sample_condition.field == "tags"
    assert sample_condition.value == "pii"


def test_condition_to_dict(sample_condition):
    """Test converting condition to dictionary."""
    data = sample_condition.to_dict()

    assert data["condition_type"] == "asset_tag"
    assert data["operator"] == "contains"
    assert data["field"] == "tags"
    assert data["value"] == "pii"


def test_condition_from_dict():
    """Test creating condition from dictionary."""
    data = {
        "condition_type": "risk_tier",
        "operator": "in",
        "field": "risk_tier",
        "value": ["HIGH", "CRITICAL"],
        "and_conditions": [],
        "or_conditions": [],
        "not_condition": None,
    }

    condition = PolicyCondition.from_dict(data)

    assert condition.condition_type == ConditionType.RISK_TIER
    assert condition.operator == ConditionOperator.IN
    assert condition.value == ["HIGH", "CRITICAL"]


def test_condition_with_and_logic():
    """Test condition with AND logic."""
    _ = PolicyCondition(
        condition_type=ConditionType.ASSET_TAG,
        operator=ConditionOperator.CONTAINS,
        field="tags",
        value="pii",
    )

    condition2 = PolicyCondition(
        condition_type=ConditionType.LOCATION,
        operator=ConditionOperator.EQUALS,
        field="location",
        value="production",
    )

    combined = PolicyCondition(
        condition_type=ConditionType.ASSET_TAG,
        operator=ConditionOperator.CONTAINS,
        field="tags",
        value="pii",
        and_conditions=[condition2],
    )

    assert len(combined.and_conditions) == 1
    assert combined.and_conditions[0].condition_type == ConditionType.LOCATION


def test_condition_with_or_logic():
    """Test condition with OR logic."""
    _ = PolicyCondition(
        condition_type=ConditionType.RISK_TIER,
        operator=ConditionOperator.EQUALS,
        field="risk_tier",
        value="HIGH",
    )

    condition2 = PolicyCondition(
        condition_type=ConditionType.RISK_TIER,
        operator=ConditionOperator.EQUALS,
        field="risk_tier",
        value="CRITICAL",
    )

    combined = PolicyCondition(
        condition_type=ConditionType.RISK_TIER,
        operator=ConditionOperator.EQUALS,
        field="risk_tier",
        value="HIGH",
        or_conditions=[condition2],
    )

    assert len(combined.or_conditions) == 1


def test_condition_with_not_logic():
    """Test condition with NOT logic."""
    inner = PolicyCondition(
        condition_type=ConditionType.ASSET_STATUS,
        operator=ConditionOperator.EQUALS,
        field="status",
        value="deprecated",
    )

    condition = PolicyCondition(
        condition_type=ConditionType.ASSET_STATUS,
        operator=ConditionOperator.EQUALS,
        field="status",
        value="active",
        not_condition=inner,
    )

    assert condition.not_condition is not None
    assert condition.not_condition.value == "deprecated"


# ============================================================================
# PolicyAction Tests
# ============================================================================


def test_action_creation(sample_action):
    """Test creating a policy action."""
    assert sample_action.action_type == ActionType.REQUIRE_APPROVAL
    assert sample_action.parameters["min_authority_level"] == 3


def test_action_to_dict(sample_action):
    """Test converting action to dictionary."""
    data = sample_action.to_dict()

    assert data["action_type"] == "require_approval"
    assert data["parameters"]["min_authority_level"] == 3


def test_action_from_dict():
    """Test creating action from dictionary."""
    data = {
        "action_type": "deny",
        "parameters": {"reason": "Test denial"},
    }

    action = PolicyAction.from_dict(data)

    assert action.action_type == ActionType.DENY
    assert action.parameters["reason"] == "Test denial"


def test_action_types():
    """Test all action types."""
    actions = [
        PolicyAction(ActionType.ALLOW, {}),
        PolicyAction(ActionType.DENY, {"reason": "test"}),
        PolicyAction(ActionType.REQUIRE_APPROVAL, {"min_authority_level": 3}),
        PolicyAction(ActionType.ADD_TAG, {"tags": ["test"]}),
        PolicyAction(ActionType.SEND_ALERT, {"recipients": ["admin"]}),
        PolicyAction(ActionType.LOG_EVENT, {"event_type": "test"}),
        PolicyAction(ActionType.ESCALATE, {}),
    ]

    assert len(actions) == 7
    assert all(isinstance(a, PolicyAction) for a in actions)


# ============================================================================
# Policy Tests
# ============================================================================


def test_policy_creation(sample_policy):
    """Test creating a policy."""
    assert sample_policy.name == "Test Policy"
    assert sample_policy.status == PolicyStatus.DRAFT
    assert len(sample_policy.conditions) == 1
    assert len(sample_policy.actions) == 1


def test_policy_to_dict(sample_policy):
    """Test converting policy to dictionary."""
    data = sample_policy.to_dict()

    assert data["name"] == "Test Policy"
    assert data["status"] == "draft"
    assert len(data["conditions"]) == 1
    assert len(data["actions"]) == 1


def test_policy_from_dict(sample_policy):
    """Test creating policy from dictionary."""
    data = sample_policy.to_dict()
    policy = Policy.from_dict(data)

    assert policy.name == sample_policy.name
    assert policy.status == sample_policy.status


def test_policy_with_inheritance():
    """Test policy with parent inheritance."""
    now = datetime.utcnow()

    _ = Policy(
        policy_id="parent-001",
        name="Parent Policy",
        description="Parent",
        version="1.0",
        status=PolicyStatus.ACTIVE,
        conditions=[],
        actions=[],
        created_at=now,
        created_by="test-user",
        updated_at=now,
        updated_by="test-user",
    )

    child = Policy(
        policy_id="child-001",
        name="Child Policy",
        description="Child",
        version="1.0",
        status=PolicyStatus.ACTIVE,
        conditions=[],
        actions=[],
        created_at=now,
        created_by="test-user",
        updated_at=now,
        updated_by="test-user",
        parent_policy_id="parent-001",
        override_parent=True,
    )

    assert child.parent_policy_id == "parent-001"
    assert child.override_parent is True


def test_policy_with_scope():
    """Test policy with applies_to scope."""
    now = datetime.utcnow()

    policy = Policy(
        policy_id="scoped-001",
        name="Scoped Policy",
        description="Applies only to agents",
        version="1.0",
        status=PolicyStatus.ACTIVE,
        conditions=[],
        actions=[],
        created_at=now,
        created_by="test-user",
        updated_at=now,
        updated_by="test-user",
        applies_to=["agent", "tool"],
    )

    assert "agent" in policy.applies_to
    assert "tool" in policy.applies_to


def test_policy_priority():
    """Test policy priority."""
    now = datetime.utcnow()

    high_priority = Policy(
        policy_id="high-001",
        name="High Priority",
        description="High",
        version="1.0",
        status=PolicyStatus.ACTIVE,
        conditions=[],
        actions=[],
        created_at=now,
        created_by="test-user",
        updated_at=now,
        updated_by="test-user",
        priority=100,
    )

    low_priority = Policy(
        policy_id="low-001",
        name="Low Priority",
        description="Low",
        version="1.0",
        status=PolicyStatus.ACTIVE,
        conditions=[],
        actions=[],
        created_at=now,
        created_by="test-user",
        updated_at=now,
        updated_by="test-user",
        priority=10,
    )

    assert high_priority.priority > low_priority.priority


# ============================================================================
# PolicyTemplate Tests
# ============================================================================


def test_template_creation():
    """Test creating a policy template."""
    template = PolicyTemplate(
        template_id="tmpl-test",
        name="Test Template",
        description="A test template",
        category="data_protection",
        conditions=[],
        actions=[],
        created_at=datetime.utcnow(),
        created_by="system",
    )

    assert template.name == "Test Template"
    assert template.category == "data_protection"


def test_template_instantiation():
    """Test instantiating a policy from template."""
    template = PolicyTemplate(
        template_id="tmpl-test",
        name="Test Template",
        description="A test template",
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
                parameters={"min_authority_level": 3},
            )
        ],
        created_at=datetime.utcnow(),
        created_by="system",
    )

    policy = template.instantiate("My Policy", "test-user")

    assert policy.name == "My Policy"
    assert policy.status == PolicyStatus.DRAFT
    assert len(policy.conditions) == 1
    assert len(policy.actions) == 1
    assert template.usage_count == 1


def test_template_library_gdpr():
    """Test GDPR PII protection template."""
    template = PolicyTemplateLibrary.get_gdpr_pii_protection()

    assert template.template_id == "tmpl-gdpr-pii"
    assert template.category == "data_protection"
    assert len(template.conditions) == 1
    assert len(template.actions) == 3


def test_template_library_hipaa():
    """Test HIPAA PHI protection template."""
    template = PolicyTemplateLibrary.get_hipaa_phi_protection()

    assert template.template_id == "tmpl-hipaa-phi"
    assert template.category == "data_protection"


def test_template_library_production_gate():
    """Test production deployment gate template."""
    template = PolicyTemplateLibrary.get_production_deployment_gate()

    assert template.template_id == "tmpl-prod-gate"
    assert template.category == "operational"


def test_template_library_high_risk():
    """Test high-risk approval template."""
    template = PolicyTemplateLibrary.get_high_risk_approval()

    assert template.template_id == "tmpl-high-risk"
    assert template.category == "risk_management"


def test_template_library_business_hours():
    """Test business hours restriction template."""
    template = PolicyTemplateLibrary.get_business_hours_restriction()

    assert template.template_id == "tmpl-business-hours"
    assert template.category == "operational"


def test_template_library_get_all():
    """Test getting all templates."""
    templates = PolicyTemplateLibrary.get_all_templates()

    assert len(templates) == 5
    assert all(isinstance(t, PolicyTemplate) for t in templates)


# ============================================================================
# PolicyManager Tests
# ============================================================================


def test_manager_singleton():
    """Test PolicyManager is a singleton."""
    manager1 = get_policy_manager()
    manager2 = get_policy_manager()

    assert manager1 is manager2


def test_manager_create_policy(sample_policy):
    """Test creating a policy."""
    manager = get_policy_manager()

    created = manager.create_policy(sample_policy)

    assert created.policy_id == sample_policy.policy_id
    assert created.name == sample_policy.name


def test_manager_create_duplicate_policy(sample_policy):
    """Test creating a duplicate policy raises error."""
    manager = get_policy_manager()

    manager.create_policy(sample_policy)

    with pytest.raises(ValueError, match="already exists"):
        manager.create_policy(sample_policy)


def test_manager_get_policy(sample_policy):
    """Test getting a policy by ID."""
    manager = get_policy_manager()

    manager.create_policy(sample_policy)
    retrieved = manager.get_policy(sample_policy.policy_id)

    assert retrieved is not None
    assert retrieved.policy_id == sample_policy.policy_id


def test_manager_get_nonexistent_policy():
    """Test getting a nonexistent policy returns None."""
    manager = get_policy_manager()

    policy = manager.get_policy("nonexistent")

    assert policy is None


def test_manager_list_policies(sample_policy):
    """Test listing all policies."""
    manager = get_policy_manager()

    manager.create_policy(sample_policy)
    policies = manager.list_policies()

    assert len(policies) == 1
    assert policies[0].policy_id == sample_policy.policy_id


def test_manager_list_policies_by_status(sample_policy):
    """Test listing policies filtered by status."""
    manager = get_policy_manager()

    manager.create_policy(sample_policy)
    manager.activate_policy(sample_policy.policy_id, "test-user")

    active_policies = manager.list_policies(status=PolicyStatus.ACTIVE)
    draft_policies = manager.list_policies(status=PolicyStatus.DRAFT)

    assert len(active_policies) == 1
    assert len(draft_policies) == 0


def test_manager_list_policies_by_applies_to():
    """Test listing policies filtered by applies_to."""
    manager = get_policy_manager()

    now = datetime.utcnow()

    agent_policy = Policy(
        policy_id="agent-policy",
        name="Agent Policy",
        description="For agents",
        version="1.0",
        status=PolicyStatus.ACTIVE,
        conditions=[],
        actions=[],
        created_at=now,
        created_by="test-user",
        updated_at=now,
        updated_by="test-user",
        applies_to=["agent"],
    )

    tool_policy = Policy(
        policy_id="tool-policy",
        name="Tool Policy",
        description="For tools",
        version="1.0",
        status=PolicyStatus.ACTIVE,
        conditions=[],
        actions=[],
        created_at=now,
        created_by="test-user",
        updated_at=now,
        updated_by="test-user",
        applies_to=["tool"],
    )

    manager.create_policy(agent_policy)
    manager.create_policy(tool_policy)

    agent_policies = manager.list_policies(applies_to="agent")
    tool_policies = manager.list_policies(applies_to="tool")

    assert len(agent_policies) == 1
    assert len(tool_policies) == 1


def test_manager_update_policy(sample_policy):
    """Test updating a policy."""
    manager = get_policy_manager()

    manager.create_policy(sample_policy)

    updated = manager.update_policy(
        sample_policy.policy_id,
        "test-user",
        name="Updated Policy",
        description="Updated description",
    )

    assert updated.name == "Updated Policy"
    assert updated.description == "Updated description"
    assert updated.version == "1.1"


def test_manager_update_nonexistent_policy():
    """Test updating a nonexistent policy raises error."""
    manager = get_policy_manager()

    with pytest.raises(ValueError, match="not found"):
        manager.update_policy("nonexistent", "test-user", name="Test")


def test_manager_delete_policy(sample_policy):
    """Test deleting a policy."""
    manager = get_policy_manager()

    manager.create_policy(sample_policy)
    manager.delete_policy(sample_policy.policy_id, "test-user")

    policy = manager.get_policy(sample_policy.policy_id)
    assert policy is None


def test_manager_delete_nonexistent_policy():
    """Test deleting a nonexistent policy raises error."""
    manager = get_policy_manager()

    with pytest.raises(ValueError, match="not found"):
        manager.delete_policy("nonexistent", "test-user")


def test_manager_activate_policy(sample_policy):
    """Test activating a policy."""
    manager = get_policy_manager()

    manager.create_policy(sample_policy)
    activated = manager.activate_policy(sample_policy.policy_id, "test-user")

    assert activated.status == PolicyStatus.ACTIVE


def test_manager_deactivate_policy(sample_policy):
    """Test deactivating a policy."""
    manager = get_policy_manager()

    manager.create_policy(sample_policy)
    manager.activate_policy(sample_policy.policy_id, "test-user")
    deactivated = manager.deactivate_policy(sample_policy.policy_id, "test-user")

    assert deactivated.status == PolicyStatus.DEPRECATED


def test_manager_policy_history(sample_policy):
    """Test policy change history."""
    manager = get_policy_manager()

    manager.create_policy(sample_policy)
    manager.update_policy(sample_policy.policy_id, "test-user", name="Updated")
    manager.activate_policy(sample_policy.policy_id, "test-user")

    history = manager.get_policy_history(sample_policy.policy_id)

    assert len(history) == 3
    assert history[0]["action"] == "created"
    assert history[1]["action"] == "updated"
    assert history[2]["action"] == "updated"  # activate is an update


def test_manager_list_templates():
    """Test listing templates."""
    manager = get_policy_manager()

    templates = manager.list_templates()

    assert len(templates) >= 5  # Built-in templates


def test_manager_list_templates_by_category():
    """Test listing templates by category."""
    manager = get_policy_manager()

    data_protection = manager.list_templates(category="data_protection")
    operational = manager.list_templates(category="operational")

    assert len(data_protection) >= 2  # GDPR, HIPAA
    assert len(operational) >= 2  # Production gate, business hours


def test_manager_get_template():
    """Test getting a template by ID."""
    manager = get_policy_manager()

    template = manager.get_template("tmpl-gdpr-pii")

    assert template is not None
    assert template.name == "GDPR PII Protection"


def test_manager_create_from_template():
    """Test creating a policy from template."""
    manager = get_policy_manager()

    policy = manager.create_from_template(
        "tmpl-gdpr-pii",
        "My GDPR Policy",
        "test-user",
    )

    assert policy.name == "My GDPR Policy"
    assert policy.status == PolicyStatus.DRAFT
    assert len(policy.conditions) == 1
    assert len(policy.actions) == 3


def test_manager_create_from_nonexistent_template():
    """Test creating from nonexistent template raises error."""
    manager = get_policy_manager()

    with pytest.raises(ValueError, match="not found"):
        manager.create_from_template("nonexistent", "Test", "test-user")


def test_manager_create_custom_template():
    """Test creating a custom template."""
    manager = get_policy_manager()

    template = PolicyTemplate(
        template_id="custom-001",
        name="Custom Template",
        description="A custom template",
        category="custom",
        conditions=[],
        actions=[],
        created_at=datetime.utcnow(),
        created_by="test-user",
    )

    created = manager.create_template(template)

    assert created.template_id == "custom-001"


def test_manager_create_duplicate_template():
    """Test creating duplicate template raises error."""
    manager = get_policy_manager()

    template = PolicyTemplate(
        template_id="tmpl-gdpr-pii",  # Already exists
        name="Duplicate",
        description="Duplicate",
        category="test",
        conditions=[],
        actions=[],
        created_at=datetime.utcnow(),
        created_by="test-user",
    )

    with pytest.raises(ValueError, match="already exists"):
        manager.create_template(template)


def test_manager_policy_priority_sorting():
    """Test policies are sorted by priority."""
    manager = get_policy_manager()
    now = datetime.utcnow()

    # Create policies with different priorities
    for i in range(5):
        policy = Policy(
            policy_id=f"policy-{i}",
            name=f"Policy {i}",
            description=f"Priority {i*10}",
            version="1.0",
            status=PolicyStatus.ACTIVE,
            conditions=[],
            actions=[],
            created_at=now,
            created_by="test-user",
            updated_at=now,
            updated_by="test-user",
            priority=i * 10,
        )
        manager.create_policy(policy)

    policies = manager.list_policies()

    # Should be sorted by priority descending
    assert policies[0].priority == 40
    assert policies[4].priority == 0
