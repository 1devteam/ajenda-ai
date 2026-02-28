"""
Tests for Policy Evaluator.

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
    PolicyStatus,
    ConditionType,
    ConditionOperator,
    ActionType,
    get_policy_manager,
)
from backend.agents.compliance.policy_evaluator import (
    EvaluationContext,
    PolicyEvaluationResult,
    PolicyEvaluator,
    get_policy_evaluator,
)
from backend.agents.registry.asset_registry import (

    AIAsset,
    AssetType,
    AssetStatus,
    get_registry,
)
pytestmark = pytest.mark.unit


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def clear_all():
    """Clear all managers before each test."""
    manager = get_policy_manager()
    registry = get_registry()
    evaluator = get_policy_evaluator()
    
    manager.clear()
    registry.clear()
    evaluator.clear_cache()
    
    yield
    
    manager.clear()
    registry.clear()
    evaluator.clear_cache()


@pytest.fixture
def sample_asset():
    """Create a sample asset."""
    registry = get_registry()
    
    asset = AIAsset(
        asset_id="test-agent-001",
        asset_type=AssetType.AGENT,
        name="Test Agent",
        description="A test agent",
        owner="test-user",
        status=AssetStatus.ACTIVE,
        tags=["pii", "production"],
        metadata={"location": "production"},
    )
    
    registry.register(asset)
    return asset


@pytest.fixture
def sample_context(sample_asset):
    """Create a sample evaluation context."""
    return EvaluationContext(
        asset=sample_asset,
        operation="execute",
        user_id="user-001",
        user_role="operator",
        user_authority_level=2,
        timestamp=datetime.utcnow(),
        location="production",
        data_accessed=["user_data"],
    )


# ============================================================================
# EvaluationContext Tests
# ============================================================================

def test_context_creation(sample_context):
    """Test creating an evaluation context."""
    assert sample_context.asset.asset_id == "test-agent-001"
    assert sample_context.operation == "execute"
    assert sample_context.user_id == "user-001"
    assert sample_context.user_authority_level == 2


# ============================================================================
# PolicyEvaluator Tests - Basic Evaluation
# ============================================================================

def test_evaluator_singleton():
    """Test PolicyEvaluator is a singleton."""
    evaluator1 = get_policy_evaluator()
    evaluator2 = get_policy_evaluator()
    
    assert evaluator1 is evaluator2


def test_evaluate_no_policies(sample_context):
    """Test evaluation with no active policies."""
    evaluator = get_policy_evaluator()
    
    result = evaluator.evaluate(sample_context)
    
    assert result.allowed is True
    assert len(result.policies_evaluated) == 0
    assert len(result.policies_matched) == 0


def test_evaluate_single_policy(sample_context):
    """Test evaluation with a single policy."""
    manager = get_policy_manager()
    evaluator = get_policy_evaluator()
    
    # Create a policy that matches
    now = datetime.utcnow()
    policy = Policy(
        policy_id="test-policy-001",
        name="Test Policy",
        description="Test",
        version="1.0",
        status=PolicyStatus.ACTIVE,
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
        created_at=now,
        created_by="test-user",
        updated_at=now,
        updated_by="test-user",
    )
    
    manager.create_policy(policy)
    
    result = evaluator.evaluate(sample_context)
    
    assert len(result.policies_evaluated) == 1
    assert len(result.policies_matched) == 1
    assert result.requires_approval is True


def test_evaluate_deny_action(sample_context):
    """Test evaluation with DENY action."""
    manager = get_policy_manager()
    evaluator = get_policy_evaluator()
    
    now = datetime.utcnow()
    policy = Policy(
        policy_id="deny-policy",
        name="Deny Policy",
        description="Denies operation",
        version="1.0",
        status=PolicyStatus.ACTIVE,
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
                action_type=ActionType.DENY,
                parameters={"reason": "PII access denied"},
            )
        ],
        created_at=now,
        created_by="test-user",
        updated_at=now,
        updated_by="test-user",
    )
    
    manager.create_policy(policy)
    
    result = evaluator.evaluate(sample_context)
    
    assert result.allowed is False
    assert result.reason == "PII access denied"


def test_evaluate_add_tag_action(sample_context):
    """Test evaluation with ADD_TAG action."""
    manager = get_policy_manager()
    evaluator = get_policy_evaluator()
    
    now = datetime.utcnow()
    policy = Policy(
        policy_id="tag-policy",
        name="Tag Policy",
        description="Adds tags",
        version="1.0",
        status=PolicyStatus.ACTIVE,
        conditions=[
            PolicyCondition(
                condition_type=ConditionType.LOCATION,
                operator=ConditionOperator.EQUALS,
                field="location",
                value="production",
            )
        ],
        actions=[
            PolicyAction(
                action_type=ActionType.ADD_TAG,
                parameters={"tags": ["production-verified"]},
            )
        ],
        created_at=now,
        created_by="test-user",
        updated_at=now,
        updated_by="test-user",
    )
    
    manager.create_policy(policy)
    
    result = evaluator.evaluate(sample_context)
    
    assert "production-verified" in result.tags_to_add


def test_evaluate_send_alert_action(sample_context):
    """Test evaluation with SEND_ALERT action."""
    manager = get_policy_manager()
    evaluator = get_policy_evaluator()
    
    now = datetime.utcnow()
    policy = Policy(
        policy_id="alert-policy",
        name="Alert Policy",
        description="Sends alerts",
        version="1.0",
        status=PolicyStatus.ACTIVE,
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
                action_type=ActionType.SEND_ALERT,
                parameters={
                    "recipients": ["security-team"],
                    "message": "PII access detected",
                },
            )
        ],
        created_at=now,
        created_by="test-user",
        updated_at=now,
        updated_by="test-user",
    )
    
    manager.create_policy(policy)
    
    result = evaluator.evaluate(sample_context)
    
    assert len(result.alerts_to_send) == 1
    assert "security-team" in result.alerts_to_send[0]["recipients"]


def test_evaluate_log_event_action(sample_context):
    """Test evaluation with LOG_EVENT action."""
    manager = get_policy_manager()
    evaluator = get_policy_evaluator()
    
    now = datetime.utcnow()
    policy = Policy(
        policy_id="log-policy",
        name="Log Policy",
        description="Logs events",
        version="1.0",
        status=PolicyStatus.ACTIVE,
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
                action_type=ActionType.LOG_EVENT,
                parameters={
                    "event_type": "pii_access",
                    "severity": "high",
                },
            )
        ],
        created_at=now,
        created_by="test-user",
        updated_at=now,
        updated_by="test-user",
    )
    
    manager.create_policy(policy)
    
    result = evaluator.evaluate(sample_context)
    
    assert len(result.events_to_log) == 1
    assert result.events_to_log[0]["event_type"] == "pii_access"


# ============================================================================
# Condition Evaluation Tests
# ============================================================================

def test_evaluate_equals_operator(sample_context):
    """Test EQUALS operator."""
    manager = get_policy_manager()
    evaluator = get_policy_evaluator()
    
    now = datetime.utcnow()
    policy = Policy(
        policy_id="equals-policy",
        name="Equals Policy",
        description="Tests equals",
        version="1.0",
        status=PolicyStatus.ACTIVE,
        conditions=[
            PolicyCondition(
                condition_type=ConditionType.ASSET_STATUS,
                operator=ConditionOperator.EQUALS,
                field="status",
                value="active",
            )
        ],
        actions=[
            PolicyAction(ActionType.ADD_TAG, {"tags": ["matched"]})
        ],
        created_at=now,
        created_by="test-user",
        updated_at=now,
        updated_by="test-user",
    )
    
    manager.create_policy(policy)
    
    result = evaluator.evaluate(sample_context)
    
    assert len(result.policies_matched) == 1


def test_evaluate_contains_operator(sample_context):
    """Test CONTAINS operator."""
    manager = get_policy_manager()
    evaluator = get_policy_evaluator()
    
    now = datetime.utcnow()
    policy = Policy(
        policy_id="contains-policy",
        name="Contains Policy",
        description="Tests contains",
        version="1.0",
        status=PolicyStatus.ACTIVE,
        conditions=[
            PolicyCondition(
                condition_type=ConditionType.ASSET_TAG,
                operator=ConditionOperator.CONTAINS,
                field="tags",
                value="pii",
            )
        ],
        actions=[
            PolicyAction(ActionType.ADD_TAG, {"tags": ["matched"]})
        ],
        created_at=now,
        created_by="test-user",
        updated_at=now,
        updated_by="test-user",
    )
    
    manager.create_policy(policy)
    
    result = evaluator.evaluate(sample_context)
    
    assert len(result.policies_matched) == 1


def test_evaluate_in_operator(sample_context):
    """Test IN operator."""
    manager = get_policy_manager()
    evaluator = get_policy_evaluator()
    
    now = datetime.utcnow()
    policy = Policy(
        policy_id="in-policy",
        name="In Policy",
        description="Tests in",
        version="1.0",
        status=PolicyStatus.ACTIVE,
        conditions=[
            PolicyCondition(
                condition_type=ConditionType.ASSET_STATUS,
                operator=ConditionOperator.IN,
                field="status",
                value=["active", "pending"],
            )
        ],
        actions=[
            PolicyAction(ActionType.ADD_TAG, {"tags": ["matched"]})
        ],
        created_at=now,
        created_by="test-user",
        updated_at=now,
        updated_by="test-user",
    )
    
    manager.create_policy(policy)
    
    result = evaluator.evaluate(sample_context)
    
    assert len(result.policies_matched) == 1


def test_evaluate_and_logic(sample_context):
    """Test AND logic in conditions."""
    manager = get_policy_manager()
    evaluator = get_policy_evaluator()
    
    now = datetime.utcnow()
    policy = Policy(
        policy_id="and-policy",
        name="AND Policy",
        description="Tests AND logic",
        version="1.0",
        status=PolicyStatus.ACTIVE,
        conditions=[
            PolicyCondition(
                condition_type=ConditionType.ASSET_TAG,
                operator=ConditionOperator.CONTAINS,
                field="tags",
                value="pii",
                and_conditions=[
                    PolicyCondition(
                        condition_type=ConditionType.LOCATION,
                        operator=ConditionOperator.EQUALS,
                        field="location",
                        value="production",
                    )
                ],
            )
        ],
        actions=[
            PolicyAction(ActionType.ADD_TAG, {"tags": ["matched"]})
        ],
        created_at=now,
        created_by="test-user",
        updated_at=now,
        updated_by="test-user",
    )
    
    manager.create_policy(policy)
    
    result = evaluator.evaluate(sample_context)
    
    assert len(result.policies_matched) == 1


def test_evaluate_or_logic():
    """Test OR logic in conditions."""
    registry = get_registry()
    manager = get_policy_manager()
    evaluator = get_policy_evaluator()
    
    # Create asset without PII tag
    asset = AIAsset(
        asset_id="no-pii-agent",
        asset_type=AssetType.AGENT,
        name="No PII Agent",
        description="Test",
        owner="test-user",
        status=AssetStatus.ACTIVE,
        tags=["production"],  # No PII
        metadata={"location": "production"},
    )
    registry.register(asset)
    
    context = EvaluationContext(
        asset=asset,
        operation="execute",
        user_id="user-001",
        user_role="operator",
        user_authority_level=2,
        timestamp=datetime.utcnow(),
        location="production",
    )
    
    now = datetime.utcnow()
    policy = Policy(
        policy_id="or-policy",
        name="OR Policy",
        description="Tests OR logic",
        version="1.0",
        status=PolicyStatus.ACTIVE,
        conditions=[
            PolicyCondition(
                condition_type=ConditionType.ASSET_TAG,
                operator=ConditionOperator.CONTAINS,
                field="tags",
                value="pii",
                or_conditions=[
                    PolicyCondition(
                        condition_type=ConditionType.ASSET_TAG,
                        operator=ConditionOperator.CONTAINS,
                        field="tags",
                        value="production",
                    )
                ],
            )
        ],
        actions=[
            PolicyAction(ActionType.ADD_TAG, {"tags": ["matched"]})
        ],
        created_at=now,
        created_by="test-user",
        updated_at=now,
        updated_by="test-user",
    )
    
    manager.create_policy(policy)
    
    result = evaluator.evaluate(context)
    
    # Should match because of OR (has production tag)
    assert len(result.policies_matched) == 1


# ============================================================================
# Caching Tests
# ============================================================================

def test_evaluation_caching(sample_context):
    """Test that evaluations are cached."""
    manager = get_policy_manager()
    evaluator = get_policy_evaluator()
    
    now = datetime.utcnow()
    policy = Policy(
        policy_id="cache-test",
        name="Cache Test",
        description="Test caching",
        version="1.0",
        status=PolicyStatus.ACTIVE,
        conditions=[
            PolicyCondition(
                condition_type=ConditionType.ASSET_TAG,
                operator=ConditionOperator.CONTAINS,
                field="tags",
                value="pii",
            )
        ],
        actions=[
            PolicyAction(ActionType.ADD_TAG, {"tags": ["cached"]})
        ],
        created_at=now,
        created_by="test-user",
        updated_at=now,
        updated_by="test-user",
    )
    
    manager.create_policy(policy)
    
    # First evaluation
    result1 = evaluator.evaluate(sample_context)
    
    # Second evaluation should use cache
    result2 = evaluator.evaluate(sample_context)
    
    assert result1.allowed == result2.allowed
    assert result1.policies_matched == result2.policies_matched


def test_cache_clearing(sample_context):
    """Test clearing evaluation cache."""
    evaluator = get_policy_evaluator()
    
    # Evaluate to populate cache
    evaluator.evaluate(sample_context)
    
    # Clear cache
    evaluator.clear_cache()
    
    # Cache should be empty
    assert len(evaluator._eval_cache) == 0


# ============================================================================
# Utility Tests
# ============================================================================

def test_get_applicable_policies(sample_asset):
    """Test getting applicable policies."""
    manager = get_policy_manager()
    evaluator = get_policy_evaluator()
    
    now = datetime.utcnow()
    
    # Create policies for different asset types
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
    
    agent_policies = evaluator.get_applicable_policies(asset_type="agent")
    tool_policies = evaluator.get_applicable_policies(asset_type="tool")
    
    assert len(agent_policies) == 1
    assert len(tool_policies) == 1


def test_test_policy(sample_context):
    """Test testing a policy without activating it."""
    manager = get_policy_manager()
    evaluator = get_policy_evaluator()
    
    now = datetime.utcnow()
    policy = Policy(
        policy_id="test-policy",
        name="Test Policy",
        description="Test",
        version="1.0",
        status=PolicyStatus.DRAFT,  # Not active
        conditions=[
            PolicyCondition(
                condition_type=ConditionType.ASSET_TAG,
                operator=ConditionOperator.CONTAINS,
                field="tags",
                value="pii",
            )
        ],
        actions=[
            PolicyAction(ActionType.REQUIRE_APPROVAL, {"min_authority_level": 3})
        ],
        created_at=now,
        created_by="test-user",
        updated_at=now,
        updated_by="test-user",
    )
    
    manager.create_policy(policy)
    
    # Test the policy
    result = evaluator.test_policy(policy, sample_context)
    
    assert len(result.policies_matched) == 1
    assert result.requires_approval is True


def test_evaluation_result_to_dict(sample_context):
    """Test converting evaluation result to dictionary."""
    evaluator = get_policy_evaluator()
    
    result = evaluator.evaluate(sample_context)
    data = result.to_dict()
    
    assert "allowed" in data
    assert "reason" in data
    assert "policies_evaluated" in data
    assert "policies_matched" in data
