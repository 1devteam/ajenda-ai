"""
Tests for Contextual Tagging Rule.

Author: Dev Team Lead
Date: 2026-02-26
Built with Pride for Obex Blackvault
"""

import pytest
from datetime import datetime, timedelta

from backend.agents.registry.asset_registry import (
    get_registry,
    AIAsset,
    AssetType,
    AssetStatus,
)
from backend.agents.compliance.contextual_tagging import (
    ContextualTag,
    ContextualTaggingRule,
    TagCategory,
    TagRule,
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
    # Clear before test
    reg._assets.clear()
    yield
    # Clear after test
    reg._assets.clear()


@pytest.fixture
def registry():
    """Get the registry instance."""
    return get_registry()


@pytest.fixture
def tagging_rule():
    """Get contextual tagging rule instance."""
    return ContextualTaggingRule()


@pytest.fixture
def sample_agent(registry):
    """Create and register a sample agent."""
    agent = AIAsset(
        asset_id="test-agent-001",
        asset_type=AssetType.AGENT,
        name="Test Agent",
        description="Test agent for tagging",
        owner="team-test",
        status=AssetStatus.ACTIVE,
    )
    registry.register(agent)
    return agent


# ============================================================================
# CONTEXTUAL TAG TESTS
# ============================================================================


def test_contextual_tag_creation():
    """Test creating a contextual tag."""
    tag = ContextualTag(
        name="pii",
        category=TagCategory.DATA_SENSITIVITY,
        applied_at=datetime.utcnow(),
        applied_by="auto",
        context={"data_accessed": ["email", "phone"]},
        confidence=0.9,
    )

    assert tag.name == "pii"
    assert tag.category == TagCategory.DATA_SENSITIVITY
    assert tag.confidence == 0.9
    assert not tag.is_expired()


def test_contextual_tag_expiration():
    """Test tag expiration."""
    # Create expired tag
    tag = ContextualTag(
        name="temp-tag",
        category=TagCategory.RISK_INDICATOR,
        applied_at=datetime.utcnow() - timedelta(hours=2),
        applied_by="auto",
        context={},
        confidence=1.0,
        expires_at=datetime.utcnow() - timedelta(hours=1),
    )

    assert tag.is_expired()


def test_contextual_tag_to_dict():
    """Test converting tag to dictionary."""
    tag = ContextualTag(
        name="pii",
        category=TagCategory.DATA_SENSITIVITY,
        applied_at=datetime.utcnow(),
        applied_by="auto",
        context={"test": "value"},
        confidence=0.9,
    )

    tag_dict = tag.to_dict()

    assert tag_dict["name"] == "pii"
    assert tag_dict["category"] == "data_sensitivity"
    assert tag_dict["confidence"] == 0.9
    assert tag_dict["context"] == {"test": "value"}


# ============================================================================
# TAG RULE TESTS
# ============================================================================


def test_tag_rule_matches_data_accessed():
    """Test tag rule matching on data accessed."""
    rule = TagRule(
        tag_name="pii",
        category=TagCategory.DATA_SENSITIVITY,
        risk_weight=0.7,
        conditions=[
            {
                "condition": "data_accessed",
                "patterns": ["email", "phone"],
            }
        ],
    )

    # Should match
    context = {"data_accessed": ["email", "name"]}
    assert rule.matches(context)

    # Should not match
    context = {"data_accessed": ["public_data"]}
    assert not rule.matches(context)


def test_tag_rule_matches_domain():
    """Test tag rule matching on domain."""
    rule = TagRule(
        tag_name="healthcare",
        category=TagCategory.DOMAIN,
        risk_weight=0.7,
        conditions=[
            {
                "condition": "domain",
                "value": "healthcare",
            }
        ],
    )

    # Should match
    context = {"domain": "healthcare"}
    assert rule.matches(context)

    # Should not match
    context = {"domain": "finance"}
    assert not rule.matches(context)


def test_tag_rule_matches_metadata():
    """Test tag rule matching on metadata."""
    rule = TagRule(
        tag_name="automated-decision",
        category=TagCategory.RISK_INDICATOR,
        risk_weight=0.7,
        conditions=[
            {
                "condition": "metadata",
                "field": "makes_decisions",
                "value": True,
            }
        ],
    )

    # Should match
    context = {"metadata": {"makes_decisions": True}}
    assert rule.matches(context)

    # Should not match
    context = {"metadata": {"makes_decisions": False}}
    assert not rule.matches(context)


# ============================================================================
# CONTEXTUAL TAGGING RULE TESTS
# ============================================================================


def test_tagging_rule_initialization(tagging_rule):
    """Test that tagging rule initializes with default rules."""
    assert len(tagging_rule.tag_rules) > 0

    # Check for expected default tags
    tag_names = [rule.tag_name for rule in tagging_rule.tag_rules]
    assert "pii" in tag_names
    assert "phi" in tag_names
    assert "financial" in tag_names
    assert "healthcare" in tag_names


def test_tagging_rule_pii_detection(tagging_rule, sample_agent):
    """Test PII tag detection."""
    context = {
        "asset_id": sample_agent.asset_id,
        "data_accessed": ["email", "phone", "address"],
    }

    result = tagging_rule.check(context)

    assert result.allowed
    assert "pii" in sample_agent.tags
    assert hasattr(sample_agent, "contextual_tags")
    assert "pii" in sample_agent.contextual_tags


def test_tagging_rule_phi_detection(tagging_rule, sample_agent):
    """Test PHI tag detection."""
    context = {
        "asset_id": sample_agent.asset_id,
        "data_accessed": ["patient_records", "medical_images"],
    }

    result = tagging_rule.check(context)

    assert result.allowed
    assert "phi" in sample_agent.tags
    assert "hipaa" in sample_agent.tags  # Should also trigger HIPAA


def test_tagging_rule_financial_detection(tagging_rule, sample_agent):
    """Test financial tag detection."""
    context = {
        "asset_id": sample_agent.asset_id,
        "data_accessed": ["credit_card", "bank_account"],
    }

    result = tagging_rule.check(context)

    assert result.allowed
    assert "financial" in sample_agent.tags


def test_tagging_rule_multiple_tags(tagging_rule, sample_agent):
    """Test that multiple tags can be applied."""
    context = {
        "asset_id": sample_agent.asset_id,
        "data_accessed": ["patient_records", "email"],
        "location": "production",
        "domain": "healthcare",
    }

    result = tagging_rule.check(context)

    assert result.allowed
    # Should have multiple tags
    assert len(sample_agent.tags) > 1
    assert "phi" in sample_agent.tags
    assert "pii" in sample_agent.tags
    assert "healthcare" in sample_agent.tags
    assert "user-facing" in sample_agent.tags


def test_tagging_rule_no_matches(tagging_rule, sample_agent):
    """Test when no tags match."""
    context = {
        "asset_id": sample_agent.asset_id,
        "data_accessed": ["public_data"],
    }

    result = tagging_rule.check(context)

    assert result.allowed
    assert "No contextual tags matched" in result.reason


def test_tagging_rule_missing_asset_id(tagging_rule):
    """Test error when asset_id is missing."""
    context = {
        "data_accessed": ["email"],
    }

    result = tagging_rule.check(context)

    assert not result.allowed
    assert "Asset ID is required" in result.reason


def test_tagging_rule_asset_not_found(tagging_rule):
    """Test error when asset not found."""
    context = {
        "asset_id": "nonexistent-asset",
        "data_accessed": ["email"],
    }

    result = tagging_rule.check(context)

    assert not result.allowed
    assert "not found in registry" in result.reason


def test_tagging_rule_add_custom_rule(tagging_rule, sample_agent):
    """Test adding a custom tagging rule."""
    custom_rule = TagRule(
        tag_name="custom-tag",
        category=TagCategory.RISK_INDICATOR,
        risk_weight=0.5,
        conditions=[
            {
                "condition": "metadata",
                "field": "custom_field",
                "value": "custom_value",
            }
        ],
    )

    tagging_rule.add_rule(custom_rule)

    context = {
        "asset_id": sample_agent.asset_id,
        "metadata": {"custom_field": "custom_value"},
    }

    result = tagging_rule.check(context)

    assert result.allowed
    assert "custom-tag" in sample_agent.tags


def test_tagging_rule_remove_rule(tagging_rule):
    """Test removing a tagging rule."""
    initial_count = len(tagging_rule.tag_rules)

    removed = tagging_rule.remove_rule("pii")

    assert removed
    assert len(tagging_rule.tag_rules) == initial_count - 1

    # Verify rule is gone
    tag_names = [rule.tag_name for rule in tagging_rule.tag_rules]
    assert "pii" not in tag_names


def test_tagging_rule_get_tags_for_context(tagging_rule):
    """Test getting tags for a context without applying them."""
    context = {
        "data_accessed": ["patient_records", "email"],
        "location": "production",
    }

    tags = tagging_rule.get_tags_for_context(context)

    assert len(tags) > 0
    assert "phi" in tags
    assert "pii" in tags
    assert "user-facing" in tags


# ============================================================================
# INTEGRATION TESTS
# ============================================================================


def test_tagging_with_healthcare_domain(tagging_rule, sample_agent):
    """Test tagging for healthcare domain."""
    context = {
        "asset_id": sample_agent.asset_id,
        "data_accessed": ["patient_records", "diagnoses"],
        "domain": "healthcare",
        "location": "production",
        "metadata": {"makes_decisions": True},
    }

    result = tagging_rule.check(context)

    assert result.allowed
    # Should have comprehensive healthcare tags
    assert "phi" in sample_agent.tags
    assert "healthcare" in sample_agent.tags
    assert "hipaa" in sample_agent.tags
    assert "user-facing" in sample_agent.tags
    assert "automated-decision" in sample_agent.tags
    assert "eu-ai-act" in sample_agent.tags


def test_tagging_with_finance_domain(tagging_rule, sample_agent):
    """Test tagging for finance domain."""
    context = {
        "asset_id": sample_agent.asset_id,
        "data_accessed": ["credit_card", "transactions", "financial"],
        "domain": "finance",
        "metadata": {"makes_decisions": True},
    }

    result = tagging_rule.check(context)

    assert result.allowed
    assert "financial" in sample_agent.tags
    assert "finance" in sample_agent.tags
    assert "sox" in sample_agent.tags
    assert "automated-decision" in sample_agent.tags


def test_tag_confidence_scores(tagging_rule, sample_agent):
    """Test that tags have confidence scores."""
    context = {
        "asset_id": sample_agent.asset_id,
        "data_accessed": ["email"],
    }

    result = tagging_rule.check(context)

    assert result.allowed
    assert hasattr(sample_agent, "contextual_tags")

    for tag in sample_agent.contextual_tags.values():
        assert 0.0 <= tag.confidence <= 1.0


def test_tag_context_preservation(tagging_rule, sample_agent):
    """Test that tag context is preserved."""
    context = {
        "asset_id": sample_agent.asset_id,
        "data_accessed": ["patient_records"],
        "user_role": "physician",
        "location": "production",
    }

    result = tagging_rule.check(context)

    assert result.allowed
    assert hasattr(sample_agent, "contextual_tags")

    # Check that context is preserved in tags
    for tag in sample_agent.contextual_tags.values():
        assert tag.context == context


def test_multiple_tagging_runs(tagging_rule, sample_agent):
    """Test that multiple tagging runs update tags correctly."""
    # First run
    context1 = {
        "asset_id": sample_agent.asset_id,
        "data_accessed": ["email"],
    }
    result1 = tagging_rule.check(context1)
    assert result1.allowed

    initial_tag_count = len(sample_agent.tags)

    # Second run with different context
    context2 = {
        "asset_id": sample_agent.asset_id,
        "data_accessed": ["patient_records"],
    }
    result2 = tagging_rule.check(context2)
    assert result2.allowed

    # Should have more tags now
    assert len(sample_agent.tags) > initial_tag_count
    assert "pii" in sample_agent.tags
    assert "phi" in sample_agent.tags
