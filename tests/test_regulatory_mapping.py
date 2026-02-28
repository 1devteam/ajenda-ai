"""
Tests for Regulatory Mapping and Autonomous Authority Rules.

Author: Dev Team Lead
Date: 2026-02-26
Built with Pride for Obex Blackvault
"""

import pytest
from datetime import datetime

from backend.agents.registry.asset_registry import (
    get_registry,
    AIAsset,
    AssetType,
    AssetStatus,
)
from backend.agents.compliance.regulatory_mapping import (

    RegulatoryMappingRule,
    AutonomousAuthorityRule,
    RiskLevel,
    AuthorityLevel,
    RiskAssessment,
    RiskMapping,
)
pytestmark = pytest.mark.unit


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture(autouse=True, scope="function")
def clear_registry():
    """Clear registry before and after each test."""
    from backend.agents.registry.asset_registry import get_registry
    reg = get_registry()
    reg._assets.clear()
    yield
    reg._assets.clear()


@pytest.fixture
def registry():
    """Get the registry instance."""
    return get_registry()


@pytest.fixture
def mapping_rule():
    """Get regulatory mapping rule instance."""
    return RegulatoryMappingRule()


@pytest.fixture
def authority_rule():
    """Get autonomous authority rule instance."""
    return AutonomousAuthorityRule()


@pytest.fixture
def minimal_risk_agent(registry):
    """Create agent with minimal risk tags."""
    agent = AIAsset(
        asset_id="minimal-agent",
        asset_type=AssetType.AGENT,
        name="Minimal Risk Agent",
        description="Low risk agent",
        owner="team-test",
        status=AssetStatus.ACTIVE,
        tags=["spam-filter", "general"],
    )
    registry.register(agent)
    return agent


@pytest.fixture
def limited_risk_agent(registry):
    """Create agent with limited risk tags."""
    agent = AIAsset(
        asset_id="limited-agent",
        asset_type=AssetType.AGENT,
        name="Limited Risk Agent",
        description="Limited risk agent",
        owner="team-test",
        status=AssetStatus.ACTIVE,
        tags=["chatbot", "content-generation"],
    )
    registry.register(agent)
    return agent


@pytest.fixture
def high_risk_agent(registry):
    """Create agent with high risk tags."""
    agent = AIAsset(
        asset_id="high-agent",
        asset_type=AssetType.AGENT,
        name="High Risk Agent",
        description="High risk agent",
        owner="team-test",
        status=AssetStatus.ACTIVE,
        tags=["medical-diagnosis", "biometric", "healthcare"],
    )
    registry.register(agent)
    return agent


@pytest.fixture
def unacceptable_risk_agent(registry):
    """Create agent with unacceptable risk tags."""
    agent = AIAsset(
        asset_id="unacceptable-agent",
        asset_type=AssetType.AGENT,
        name="Unacceptable Risk Agent",
        description="Prohibited agent",
        owner="team-test",
        status=AssetStatus.ACTIVE,
        tags=["social-scoring", "subliminal-manipulation"],
    )
    registry.register(agent)
    return agent


# ============================================================================
# RISK ASSESSMENT TESTS
# ============================================================================


def test_risk_assessment_creation():
    """Test creating a risk assessment."""
    assessment = RiskAssessment(
        risk_level=RiskLevel.HIGH,
        regulation="EU AI Act",
        requirements=["human-oversight", "documentation"],
        assessed_at=datetime.utcnow(),
        assessed_by="auto",
        notes="Test assessment",
    )
    
    assert assessment.risk_level == RiskLevel.HIGH
    assert assessment.regulation == "EU AI Act"
    assert len(assessment.requirements) == 2


def test_risk_assessment_to_dict():
    """Test converting risk assessment to dictionary."""
    assessment = RiskAssessment(
        risk_level=RiskLevel.HIGH,
        regulation="EU AI Act",
        requirements=["human-oversight"],
        assessed_at=datetime.utcnow(),
        assessed_by="auto",
    )
    
    assessment_dict = assessment.to_dict()
    
    assert assessment_dict["risk_level"] == "high"
    assert assessment_dict["regulation"] == "EU AI Act"
    assert "human-oversight" in assessment_dict["requirements"]


# ============================================================================
# REGULATORY MAPPING RULE TESTS
# ============================================================================


def test_mapping_rule_initialization(mapping_rule):
    """Test that mapping rule initializes with EU AI Act mappings."""
    assert len(mapping_rule.risk_mappings) > 0
    
    # Check for all risk levels
    risk_levels = [mapping.risk_level for mapping in mapping_rule.risk_mappings]
    assert RiskLevel.UNACCEPTABLE in risk_levels
    assert RiskLevel.HIGH in risk_levels
    assert RiskLevel.LIMITED in risk_levels
    assert RiskLevel.MINIMAL in risk_levels


def test_mapping_rule_minimal_risk(mapping_rule, minimal_risk_agent):
    """Test mapping minimal risk asset."""
    context = {
        "asset_id": minimal_risk_agent.asset_id,
        "tags": minimal_risk_agent.tags,
    }
    
    result = mapping_rule.check(context)
    
    assert result.allowed
    assert hasattr(minimal_risk_agent, "risk_assessment")
    assert minimal_risk_agent.risk_assessment.risk_level == RiskLevel.MINIMAL
    assert len(minimal_risk_agent.risk_assessment.requirements) == 0


def test_mapping_rule_limited_risk(mapping_rule, limited_risk_agent):
    """Test mapping limited risk asset."""
    context = {
        "asset_id": limited_risk_agent.asset_id,
        "tags": limited_risk_agent.tags,
    }
    
    result = mapping_rule.check(context)
    
    assert result.allowed
    assert limited_risk_agent.risk_assessment.risk_level == RiskLevel.LIMITED
    assert "transparency-disclosure" in limited_risk_agent.risk_assessment.requirements


def test_mapping_rule_high_risk(mapping_rule, high_risk_agent):
    """Test mapping high risk asset."""
    context = {
        "asset_id": high_risk_agent.asset_id,
        "tags": high_risk_agent.tags,
    }
    
    result = mapping_rule.check(context)
    
    assert result.allowed
    assert high_risk_agent.risk_assessment.risk_level == RiskLevel.HIGH
    assert "human-oversight" in high_risk_agent.risk_assessment.requirements
    assert "risk-assessment" in high_risk_agent.risk_assessment.requirements
    assert "technical-documentation" in high_risk_agent.risk_assessment.requirements


def test_mapping_rule_unacceptable_risk(mapping_rule, unacceptable_risk_agent):
    """Test mapping unacceptable risk asset (should be blocked)."""
    context = {
        "asset_id": unacceptable_risk_agent.asset_id,
        "tags": unacceptable_risk_agent.tags,
    }
    
    result = mapping_rule.check(context)
    
    assert not result.allowed
    assert "unacceptable risk" in result.reason.lower()
    assert "prohibited" in result.reason.lower()


def test_mapping_rule_missing_asset_id(mapping_rule):
    """Test error when asset_id is missing."""
    context = {
        "tags": ["chatbot"],
    }
    
    result = mapping_rule.check(context)
    
    assert not result.allowed
    assert "Asset ID is required" in result.reason


def test_mapping_rule_asset_not_found(mapping_rule):
    """Test error when asset not found."""
    context = {
        "asset_id": "nonexistent-asset",
    }
    
    result = mapping_rule.check(context)
    
    assert not result.allowed
    assert "not found in registry" in result.reason


def test_mapping_rule_get_risk_level(mapping_rule):
    """Test getting risk level for tags."""
    # Minimal
    assert mapping_rule.get_risk_level(["spam-filter"]) == RiskLevel.MINIMAL
    
    # Limited
    assert mapping_rule.get_risk_level(["chatbot"]) == RiskLevel.LIMITED
    
    # High
    assert mapping_rule.get_risk_level(["medical-diagnosis"]) == RiskLevel.HIGH
    
    # Unacceptable
    assert mapping_rule.get_risk_level(["social-scoring"]) == RiskLevel.UNACCEPTABLE


def test_mapping_rule_add_custom_mapping(mapping_rule):
    """Test adding a custom risk mapping."""
    custom_mapping = RiskMapping(
        risk_level=RiskLevel.HIGH,
        tags=["custom-high-risk"],
        requirements=["custom-requirement"],
        action="require_oversight",
    )
    
    mapping_rule.add_mapping(custom_mapping)
    
    risk_level = mapping_rule.get_risk_level(["custom-high-risk"])
    assert risk_level == RiskLevel.HIGH


# ============================================================================
# AUTONOMOUS AUTHORITY RULE TESTS
# ============================================================================


def test_authority_rule_guest_minimal_risk(authority_rule, minimal_risk_agent, mapping_rule):
    """Test guest can access minimal risk."""
    # First assess risk
    mapping_rule.check({"asset_id": minimal_risk_agent.asset_id})
    
    context = {
        "user_id": "guest-001",
        "user_authority_level": AuthorityLevel.GUEST,
        "asset_id": minimal_risk_agent.asset_id,
    }
    
    result = authority_rule.check(context)
    
    assert result.allowed


def test_authority_rule_guest_limited_risk(authority_rule, limited_risk_agent, mapping_rule):
    """Test guest cannot access limited risk."""
    # First assess risk
    mapping_rule.check({"asset_id": limited_risk_agent.asset_id})
    
    context = {
        "user_id": "guest-001",
        "user_authority_level": AuthorityLevel.GUEST,
        "asset_id": limited_risk_agent.asset_id,
    }
    
    result = authority_rule.check(context)
    
    assert not result.allowed
    assert "cannot access limited-risk" in result.reason.lower()


def test_authority_rule_user_limited_risk(authority_rule, limited_risk_agent, mapping_rule):
    """Test user can access limited risk."""
    # First assess risk
    mapping_rule.check({"asset_id": limited_risk_agent.asset_id})
    
    context = {
        "user_id": "user-001",
        "user_authority_level": AuthorityLevel.USER,
        "asset_id": limited_risk_agent.asset_id,
    }
    
    result = authority_rule.check(context)
    
    assert result.allowed


def test_authority_rule_user_high_risk(authority_rule, high_risk_agent, mapping_rule):
    """Test user cannot access high risk."""
    # First assess risk
    mapping_rule.check({"asset_id": high_risk_agent.asset_id})
    
    context = {
        "user_id": "user-001",
        "user_authority_level": AuthorityLevel.USER,
        "asset_id": high_risk_agent.asset_id,
    }
    
    result = authority_rule.check(context)
    
    assert not result.allowed


def test_authority_rule_operator_high_risk_with_oversight(authority_rule, high_risk_agent, mapping_rule):
    """Test operator can access high risk with oversight."""
    # First assess risk
    mapping_rule.check({"asset_id": high_risk_agent.asset_id})
    
    context = {
        "user_id": "operator-001",
        "user_authority_level": AuthorityLevel.OPERATOR,
        "asset_id": high_risk_agent.asset_id,
        "human_oversight": True,
    }
    
    result = authority_rule.check(context)
    
    assert result.allowed
    assert "with human oversight" in result.reason


def test_authority_rule_operator_high_risk_without_oversight(authority_rule, high_risk_agent, mapping_rule):
    """Test operator cannot access high risk without oversight."""
    # First assess risk
    mapping_rule.check({"asset_id": high_risk_agent.asset_id})
    
    context = {
        "user_id": "operator-001",
        "user_authority_level": AuthorityLevel.OPERATOR,
        "asset_id": high_risk_agent.asset_id,
        "human_oversight": False,
    }
    
    result = authority_rule.check(context)
    
    assert not result.allowed
    assert "without human oversight" in result.reason.lower()


def test_authority_rule_admin_high_risk(authority_rule, high_risk_agent, mapping_rule):
    """Test admin can access high risk without oversight."""
    # First assess risk
    mapping_rule.check({"asset_id": high_risk_agent.asset_id})
    
    context = {
        "user_id": "admin-001",
        "user_authority_level": AuthorityLevel.ADMIN,
        "asset_id": high_risk_agent.asset_id,
    }
    
    result = authority_rule.check(context)
    
    assert result.allowed


def test_authority_rule_admin_unacceptable_risk(authority_rule, unacceptable_risk_agent, mapping_rule):
    """Test admin cannot access unacceptable risk."""
    # First assess risk (will be blocked but assessment stored)
    mapping_rule.check({"asset_id": unacceptable_risk_agent.asset_id})
    
    # Manually set risk assessment for testing
    from backend.agents.compliance.regulatory_mapping import RiskAssessment
    unacceptable_risk_agent.risk_assessment = RiskAssessment(
        risk_level=RiskLevel.UNACCEPTABLE,
        regulation="EU AI Act",
        requirements=[],
        assessed_at=datetime.utcnow(),
        assessed_by="auto",
    )
    
    context = {
        "user_id": "admin-001",
        "user_authority_level": AuthorityLevel.ADMIN,
        "asset_id": unacceptable_risk_agent.asset_id,
    }
    
    result = authority_rule.check(context)
    
    assert not result.allowed
    assert "unacceptable risk" in result.reason.lower()


def test_authority_rule_compliance_officer_override(authority_rule, unacceptable_risk_agent):
    """Test compliance officer can override unacceptable risk."""
    # Manually set risk assessment
    from backend.agents.compliance.regulatory_mapping import RiskAssessment
    unacceptable_risk_agent.risk_assessment = RiskAssessment(
        risk_level=RiskLevel.UNACCEPTABLE,
        regulation="EU AI Act",
        requirements=[],
        assessed_at=datetime.utcnow(),
        assessed_by="auto",
    )
    
    context = {
        "user_id": "compliance-001",
        "user_authority_level": AuthorityLevel.COMPLIANCE_OFFICER,
        "asset_id": unacceptable_risk_agent.asset_id,
    }
    
    result = authority_rule.check(context)
    
    assert result.allowed


def test_authority_rule_missing_user_id(authority_rule):
    """Test error when user_id is missing."""
    context = {
        "user_authority_level": AuthorityLevel.USER,
        "asset_id": "test-asset",
    }
    
    result = authority_rule.check(context)
    
    assert not result.allowed
    assert "User ID is required" in result.reason


def test_authority_rule_missing_authority_level(authority_rule):
    """Test error when authority level is missing."""
    context = {
        "user_id": "user-001",
        "asset_id": "test-asset",
    }
    
    result = authority_rule.check(context)
    
    assert not result.allowed
    assert "authority level is required" in result.reason.lower()


def test_authority_rule_missing_asset_id(authority_rule):
    """Test error when asset_id is missing."""
    context = {
        "user_id": "user-001",
        "user_authority_level": AuthorityLevel.USER,
    }
    
    result = authority_rule.check(context)
    
    assert not result.allowed
    assert "Asset ID is required" in result.reason


# ============================================================================
# INTEGRATION TESTS
# ============================================================================


def test_full_risk_workflow(mapping_rule, authority_rule, registry):
    """Test complete workflow: tagging -> mapping -> authority."""
    # Create agent
    agent = AIAsset(
        asset_id="workflow-agent",
        asset_type=AssetType.AGENT,
        name="Workflow Agent",
        description="Test workflow",
        owner="team-test",
        status=AssetStatus.ACTIVE,
        tags=["medical-diagnosis", "healthcare"],
    )
    registry.register(agent)
    
    # Step 1: Map to risk level
    mapping_context = {
        "asset_id": agent.asset_id,
        "tags": agent.tags,
    }
    mapping_result = mapping_rule.check(mapping_context)
    
    assert mapping_result.allowed
    assert agent.risk_assessment.risk_level == RiskLevel.HIGH
    
    # Step 2: Check authority for operator with oversight
    authority_context = {
        "user_id": "operator-001",
        "user_authority_level": AuthorityLevel.OPERATOR,
        "asset_id": agent.asset_id,
        "human_oversight": True,
    }
    authority_result = authority_rule.check(authority_context)
    
    assert authority_result.allowed
    
    # Step 3: Check authority for user (should fail)
    authority_context["user_id"] = "user-001"
    authority_context["user_authority_level"] = AuthorityLevel.USER
    authority_result = authority_rule.check(authority_context)
    
    assert not authority_result.allowed


def test_risk_level_hierarchy(mapping_rule):
    """Test that higher risk levels take precedence."""
    # Agent with both high and limited risk tags
    tags = ["medical-diagnosis", "chatbot"]
    
    risk_level = mapping_rule.get_risk_level(tags)
    
    # Should be high risk (higher precedence)
    assert risk_level == RiskLevel.HIGH


def test_authority_level_hierarchy(authority_rule, registry):
    """Test authority level hierarchy."""
    # Create high risk agent
    agent = AIAsset(
        asset_id="hierarchy-agent",
        asset_type=AssetType.AGENT,
        name="Hierarchy Agent",
        description="Test hierarchy",
        owner="team-test",
        status=AssetStatus.ACTIVE,
    )
    registry.register(agent)
    
    # Set high risk
    from backend.agents.compliance.regulatory_mapping import RiskAssessment
    agent.risk_assessment = RiskAssessment(
        risk_level=RiskLevel.HIGH,
        regulation="EU AI Act",
        requirements=["human-oversight"],
        assessed_at=datetime.utcnow(),
        assessed_by="auto",
    )
    
    # Test each authority level
    base_context = {
        "asset_id": agent.asset_id,
        "human_oversight": False,
    }
    
    # Guest - denied
    context = {**base_context, "user_id": "guest", "user_authority_level": AuthorityLevel.GUEST}
    assert not authority_rule.check(context).allowed
    
    # User - denied
    context = {**base_context, "user_id": "user", "user_authority_level": AuthorityLevel.USER}
    assert not authority_rule.check(context).allowed
    
    # Operator without oversight - denied
    context = {**base_context, "user_id": "operator", "user_authority_level": AuthorityLevel.OPERATOR}
    assert not authority_rule.check(context).allowed
    
    # Admin - allowed
    context = {**base_context, "user_id": "admin", "user_authority_level": AuthorityLevel.ADMIN}
    assert authority_rule.check(context).allowed
    
    # Compliance Officer - allowed
    context = {**base_context, "user_id": "compliance", "user_authority_level": AuthorityLevel.COMPLIANCE_OFFICER}
    assert authority_rule.check(context).allowed
