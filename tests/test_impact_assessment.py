"""
Tests for Impact Assessment.

Author: Dev Team Lead
Date: 2026-02-26
Built with Pride for Obex Blackvault
"""

import pytest
from datetime import datetime, timedelta

from backend.agents.compliance.impact_assessment import (
    get_impact_assessor,
    ImpactDimension,
)
from backend.agents.compliance.risk_scoring import RiskTier, RiskScore
from backend.agents.compliance.regulatory_mapping import RiskLevel, RiskAssessment
from backend.agents.registry.asset_registry import get_registry, AIAsset, AssetType, AssetStatus
pytestmark = pytest.mark.unit



@pytest.fixture(autouse=True)
def clear_state():
    """Clear all state before each test."""
    registry = get_registry()
    registry.clear()
    
    yield
    
    registry.clear()


@pytest.fixture
def sample_low_impact_asset():
    """Create a low impact asset."""
    return AIAsset(
        asset_id="low-impact-001",
        asset_type=AssetType.AGENT,
        name="Low Impact Agent",
        description="Development agent",
        owner="test-owner",
        status=AssetStatus.ACTIVE,
        tags=["development"],
        metadata={},
    )


@pytest.fixture
def sample_high_impact_asset():
    """Create a high impact asset."""
    asset = AIAsset(
        asset_id="high-impact-001",
        asset_type=AssetType.AGENT,
        name="High Impact Agent",
        description="Production agent with high impact",
        owner="test-owner",
        status=AssetStatus.ACTIVE,
        tags=["phi", "user-facing", "production"],
        metadata={
            "revenue_at_risk": 2000000,
            "customers_affected": 15000,
            "regulatory_penalties_risk": True,
            "reputational_risk": True,
            "data_volume_gb": 500,
            "rto_hours": 2,
        },
    )
    
    # Add risk assessment
    asset.risk_assessment = RiskAssessment(
        risk_level=RiskLevel.HIGH,
        regulation="EU AI Act",
        requirements=["human-oversight", "documentation", "testing", "audit", "transparency"],
        assessed_at=datetime.utcnow(),
        assessed_by="test",
    )
    
    return asset


@pytest.fixture
def sample_asset_with_dependencies():
    """Create an asset with dependencies."""
    # Create main asset
    main_asset = AIAsset(
        asset_id="main-001",
        asset_type=AssetType.AGENT,
        name="Main Agent",
        description="Main agent",
        owner="test-owner",
        status=AssetStatus.ACTIVE,
        tags=[],
        metadata={},
    )
    
    # Create dependent assets
    dependent1 = AIAsset(
        asset_id="dep-001",
        asset_type=AssetType.AGENT,
        name="Dependent 1",
        description="Dependent agent 1",
        owner="test-owner",
        status=AssetStatus.ACTIVE,
        tags=[],
        metadata={},
        dependencies=["main-001"],
    )
    
    dependent2 = AIAsset(
        asset_id="dep-002",
        asset_type=AssetType.AGENT,
        name="Dependent 2",
        description="Dependent agent 2",
        owner="test-owner",
        status=AssetStatus.ACTIVE,
        tags=[],
        metadata={},
        dependencies=["main-001"],
    )
    
    registry = get_registry()
    registry.register(main_asset)
    registry.register(dependent1)
    registry.register(dependent2)
    
    return main_asset


# ============================================================================
# Impact Assessment Tests
# ============================================================================

def test_assess_impact_low(sample_low_impact_asset):
    """Test impact assessment for low impact asset."""
    registry = get_registry()
    registry.register(sample_low_impact_asset)
    
    assessor = get_impact_assessor()
    impact = assessor.assess_impact("low-impact-001")
    
    assert impact.asset_id == "low-impact-001"
    assert impact.overall_impact >= 0
    assert impact.overall_impact < 50  # Should be low impact
    assert impact.business_impact >= 0
    assert impact.technical_impact >= 0
    assert impact.compliance_impact >= 0


def test_assess_impact_high(sample_high_impact_asset):
    """Test impact assessment for high impact asset."""
    registry = get_registry()
    registry.register(sample_high_impact_asset)
    
    assessor = get_impact_assessor()
    impact = assessor.assess_impact("high-impact-001")
    
    assert impact.asset_id == "high-impact-001"
    assert impact.overall_impact > 50  # Should be high impact
    assert impact.business_impact > 0
    assert impact.technical_impact > 0
    assert impact.compliance_impact > 0


def test_assess_impact_not_found():
    """Test impact assessment for non-existent asset."""
    assessor = get_impact_assessor()
    
    with pytest.raises(ValueError, match="not found"):
        assessor.assess_impact("nonexistent")


# ============================================================================
# Business Impact Tests
# ============================================================================

def test_business_impact_revenue_risk(sample_high_impact_asset):
    """Test business impact from revenue at risk."""
    registry = get_registry()
    registry.register(sample_high_impact_asset)
    
    assessor = get_impact_assessor()
    impact = assessor.assess_impact("high-impact-001")
    
    # High revenue at risk should contribute to business impact
    assert impact.business_impact > 0


def test_business_impact_customers_affected(sample_high_impact_asset):
    """Test business impact from customers affected."""
    registry = get_registry()
    registry.register(sample_high_impact_asset)
    
    assessor = get_impact_assessor()
    impact = assessor.assess_impact("high-impact-001")
    
    # Many customers affected should contribute
    assert impact.business_impact > 0


def test_business_impact_regulatory_penalties():
    """Test business impact from regulatory penalties risk."""
    asset = AIAsset(
        asset_id="test-001",
        asset_type=AssetType.AGENT,
        name="Test Agent",
        description="Test",
        owner="test",
        status=AssetStatus.ACTIVE,
        tags=[],
        metadata={"regulatory_penalties_risk": True},
    )
    
    registry = get_registry()
    registry.register(asset)
    
    assessor = get_impact_assessor()
    impact = assessor.assess_impact("test-001")
    
    assert impact.business_impact >= 20  # Should add 20 points


def test_business_impact_user_facing_tag():
    """Test business impact from user-facing tag."""
    asset = AIAsset(
        asset_id="test-001",
        asset_type=AssetType.AGENT,
        name="Test Agent",
        description="Test",
        owner="test",
        status=AssetStatus.ACTIVE,
        tags=["user-facing"],
        metadata={},
    )
    
    registry = get_registry()
    registry.register(asset)
    
    assessor = get_impact_assessor()
    impact = assessor.assess_impact("test-001")
    
    assert impact.business_impact >= 15


# ============================================================================
# Technical Impact Tests
# ============================================================================

def test_technical_impact_dependencies(sample_asset_with_dependencies):
    """Test technical impact from dependencies."""
    assessor = get_impact_assessor()
    impact = assessor.assess_impact("main-001")
    
    # Should have 2 dependents
    assert impact.blast_radius == 2
    assert impact.technical_impact > 0


def test_technical_impact_data_volume(sample_high_impact_asset):
    """Test technical impact from data volume."""
    registry = get_registry()
    registry.register(sample_high_impact_asset)
    
    assessor = get_impact_assessor()
    impact = assessor.assess_impact("high-impact-001")
    
    # High data volume should contribute
    assert impact.technical_impact > 0


def test_technical_impact_rto(sample_high_impact_asset):
    """Test technical impact from RTO."""
    registry = get_registry()
    registry.register(sample_high_impact_asset)
    
    assessor = get_impact_assessor()
    impact = assessor.assess_impact("high-impact-001")
    
    # Low RTO (2 hours) should contribute
    assert impact.technical_impact > 0


# ============================================================================
# Compliance Impact Tests
# ============================================================================

def test_compliance_impact_requirements(sample_high_impact_asset):
    """Test compliance impact from requirements."""
    registry = get_registry()
    registry.register(sample_high_impact_asset)
    
    assessor = get_impact_assessor()
    impact = assessor.assess_impact("high-impact-001")
    
    # Many requirements should contribute
    assert impact.compliance_impact > 0


def test_compliance_impact_tags():
    """Test compliance impact from compliance tags."""
    asset = AIAsset(
        asset_id="test-001",
        asset_type=AssetType.AGENT,
        name="Test Agent",
        description="Test",
        owner="test",
        status=AssetStatus.ACTIVE,
        tags=["gdpr", "hipaa", "sox"],
        metadata={},
    )
    
    registry = get_registry()
    registry.register(asset)
    
    assessor = get_impact_assessor()
    impact = assessor.assess_impact("test-001")
    
    # 3 compliance tags * 15 points = 45
    assert impact.compliance_impact >= 45


def test_compliance_impact_audit_required():
    """Test compliance impact from audit requirement."""
    asset = AIAsset(
        asset_id="test-001",
        asset_type=AssetType.AGENT,
        name="Test Agent",
        description="Test",
        owner="test",
        status=AssetStatus.ACTIVE,
        tags=[],
        metadata={"audit_required": True},
    )
    
    registry = get_registry()
    registry.register(asset)
    
    assessor = get_impact_assessor()
    impact = assessor.assess_impact("test-001")
    
    assert impact.compliance_impact >= 20


# ============================================================================
# Blast Radius Tests
# ============================================================================

def test_calculate_blast_radius_no_dependents(sample_low_impact_asset):
    """Test blast radius calculation with no dependents."""
    registry = get_registry()
    registry.register(sample_low_impact_asset)
    
    assessor = get_impact_assessor()
    blast_radius = assessor.calculate_blast_radius("low-impact-001")
    
    assert blast_radius == 0


def test_calculate_blast_radius_with_dependents(sample_asset_with_dependencies):
    """Test blast radius calculation with dependents."""
    assessor = get_impact_assessor()
    blast_radius = assessor.calculate_blast_radius("main-001")
    
    assert blast_radius == 2


def test_calculate_blast_radius_recursive():
    """Test recursive blast radius calculation."""
    registry = get_registry()
    
    # Create chain: main -> dep1 -> dep2
    main = AIAsset(
        asset_id="main-001",
        asset_type=AssetType.AGENT,
        name="Main",
        description="Main",
        owner="test",
        status=AssetStatus.ACTIVE,
        tags=[],
        metadata={},
    )
    
    dep1 = AIAsset(
        asset_id="dep-001",
        asset_type=AssetType.AGENT,
        name="Dep 1",
        description="Dep 1",
        owner="test",
        status=AssetStatus.ACTIVE,
        tags=[],
        metadata={},
        dependencies=["main-001"],
    )
    
    dep2 = AIAsset(
        asset_id="dep-002",
        asset_type=AssetType.AGENT,
        name="Dep 2",
        description="Dep 2",
        owner="test",
        status=AssetStatus.ACTIVE,
        tags=[],
        metadata={},
        dependencies=["dep-001"],
    )
    
    registry.register(main)
    registry.register(dep1)
    registry.register(dep2)
    
    assessor = get_impact_assessor()
    blast_radius = assessor.calculate_blast_radius("main-001")
    
    # Should count both direct and indirect dependents
    assert blast_radius == 2


# ============================================================================
# Recovery Time Tests
# ============================================================================

def test_estimate_recovery_time_from_metadata(sample_high_impact_asset):
    """Test RTO estimation from metadata."""
    registry = get_registry()
    registry.register(sample_high_impact_asset)
    
    assessor = get_impact_assessor()
    rto = assessor.estimate_recovery_time("high-impact-001")
    
    # Should be 2 hours from metadata
    assert rto == timedelta(hours=2)


def test_estimate_recovery_time_from_risk_tier():
    """Test RTO estimation from risk tier."""
    asset = AIAsset(
        asset_id="test-001",
        asset_type=AssetType.AGENT,
        name="Test Agent",
        description="Test",
        owner="test",
        status=AssetStatus.ACTIVE,
        tags=[],
        metadata={},
    )
    
    # Add risk score
    asset.risk_score = RiskScore(
        asset_id="test-001",
        score=85.0,
        tier=RiskTier.CRITICAL,
        breakdown={},
        calculated_at=datetime.utcnow(),
        calculated_by="test",
    )
    
    registry = get_registry()
    registry.register(asset)
    
    assessor = get_impact_assessor()
    rto = assessor.estimate_recovery_time("test-001")
    
    # Critical should be 1 hour
    assert rto == timedelta(hours=1)


def test_estimate_recovery_time_default(sample_low_impact_asset):
    """Test default RTO estimation."""
    registry = get_registry()
    registry.register(sample_low_impact_asset)
    
    assessor = get_impact_assessor()
    rto = assessor.estimate_recovery_time("low-impact-001")
    
    # Default should be 24 hours
    assert rto == timedelta(hours=24)


# ============================================================================
# Mitigation Strategy Tests
# ============================================================================

def test_get_mitigation_strategies_critical():
    """Test getting mitigation strategies for critical risk."""
    assessor = get_impact_assessor()
    strategies = assessor.get_mitigation_strategies(RiskTier.CRITICAL)
    
    assert len(strategies) > 0
    assert all(s.risk_tier == RiskTier.CRITICAL for s in strategies)
    assert any(s.required for s in strategies)  # Should have required strategies


def test_get_mitigation_strategies_high():
    """Test getting mitigation strategies for high risk."""
    assessor = get_impact_assessor()
    strategies = assessor.get_mitigation_strategies(RiskTier.HIGH)
    
    assert len(strategies) > 0
    assert all(s.risk_tier == RiskTier.HIGH for s in strategies)


def test_get_mitigation_strategies_medium():
    """Test getting mitigation strategies for medium risk."""
    assessor = get_impact_assessor()
    strategies = assessor.get_mitigation_strategies(RiskTier.MEDIUM)
    
    assert len(strategies) > 0
    assert all(s.risk_tier == RiskTier.MEDIUM for s in strategies)


def test_get_mitigation_strategies_low():
    """Test getting mitigation strategies for low risk."""
    assessor = get_impact_assessor()
    strategies = assessor.get_mitigation_strategies(RiskTier.LOW)
    
    assert len(strategies) > 0
    assert all(s.risk_tier == RiskTier.LOW for s in strategies)


def test_get_mitigation_strategies_minimal():
    """Test getting mitigation strategies for minimal risk."""
    assessor = get_impact_assessor()
    strategies = assessor.get_mitigation_strategies(RiskTier.MINIMAL)
    
    assert len(strategies) >= 0
    assert all(s.risk_tier == RiskTier.MINIMAL for s in strategies)


def test_mitigation_strategy_attributes():
    """Test mitigation strategy attributes."""
    assessor = get_impact_assessor()
    strategies = assessor.get_mitigation_strategies(RiskTier.CRITICAL)
    
    for strategy in strategies:
        assert strategy.strategy_id is not None
        assert strategy.name is not None
        assert strategy.description is not None
        assert strategy.implementation_effort in ["Low", "Medium", "High"]
        assert 0 <= strategy.effectiveness <= 1


# ============================================================================
# Edge Cases Tests
# ============================================================================

def test_assess_impact_no_metadata(sample_low_impact_asset):
    """Test impact assessment with no metadata."""
    sample_low_impact_asset.metadata = {}
    
    registry = get_registry()
    registry.register(sample_low_impact_asset)
    
    assessor = get_impact_assessor()
    impact = assessor.assess_impact("low-impact-001")
    
    # Should still calculate impact
    assert impact.overall_impact >= 0


def test_assess_impact_no_tags(sample_low_impact_asset):
    """Test impact assessment with no tags."""
    sample_low_impact_asset.tags = []
    
    registry = get_registry()
    registry.register(sample_low_impact_asset)
    
    assessor = get_impact_assessor()
    impact = assessor.assess_impact("low-impact-001")
    
    # Should still calculate impact
    assert impact.overall_impact >= 0


def test_assess_impact_no_risk_assessment(sample_low_impact_asset):
    """Test impact assessment without risk assessment."""
    registry = get_registry()
    registry.register(sample_low_impact_asset)
    
    assessor = get_impact_assessor()
    impact = assessor.assess_impact("low-impact-001")
    
    # Should still calculate impact
    assert impact.compliance_impact >= 0


def test_singleton_instance():
    """Test that impact assessor is a singleton."""
    assessor1 = get_impact_assessor()
    assessor2 = get_impact_assessor()
    
    assert assessor1 is assessor2
