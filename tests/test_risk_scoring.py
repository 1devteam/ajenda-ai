"""
Tests for Risk Scoring Engine.

Author: Dev Team Lead
Date: 2026-02-26
Built with Pride for Obex Blackvault
"""

import pytest
from datetime import datetime, timedelta

from backend.agents.compliance.risk_scoring import (
    get_risk_scoring_engine,
    RiskTier,
    RiskFactor,
    RiskScore,
)
from backend.agents.compliance.regulatory_mapping import RiskLevel, RiskAssessment
from backend.agents.registry.asset_registry import get_registry, AIAsset, AssetType, AssetStatus
from backend.agents.registry.lineage_tracker import get_tracker


@pytest.fixture(autouse=True)
def clear_state():
    """Clear all state before each test."""
    registry = get_registry()
    registry.clear()
    
    tracker = get_tracker()
    tracker._events.clear()
    
    yield
    
    # Cleanup after test
    registry.clear()
    tracker._events.clear()


@pytest.fixture
def sample_minimal_asset():
    """Create a minimal risk asset."""
    return AIAsset(
        asset_id="minimal-001",
        asset_type=AssetType.AGENT,
        name="Minimal Agent",
        description="Low risk agent",
        owner="test-owner",
        status=AssetStatus.ACTIVE,
        tags=["development"],
        metadata={},
    )


@pytest.fixture
def sample_high_risk_asset():
    """Create a high risk asset."""
    asset = AIAsset(
        asset_id="high-001",
        asset_type=AssetType.AGENT,
        name="Medical Agent",
        description="High risk medical diagnosis agent",
        owner="test-owner",
        status=AssetStatus.ACTIVE,
        tags=["phi", "healthcare", "user-facing", "production", "automated-decision"],
        metadata={
            "makes_decisions": True,
            "user_facing": True,
            "location": "production",
        },
    )
    
    # Add risk assessment
    asset.risk_assessment = RiskAssessment(
        risk_level=RiskLevel.HIGH,
        regulation="EU AI Act",
        requirements=["human-oversight", "documentation"],
        assessed_at=datetime.utcnow(),
        assessed_by="test",
    )
    
    return asset


@pytest.fixture
def sample_critical_asset():
    """Create a critical risk asset."""
    asset = AIAsset(
        asset_id="critical-001",
        asset_type=AssetType.AGENT,
        name="Credit Scoring Agent",
        description="Critical risk credit scoring system",
        owner="test-owner",
        status=AssetStatus.ACTIVE,
        tags=["financial", "pii", "biometric", "user-facing", "production", "automated-decision"],
        metadata={
            "makes_decisions": True,
            "user_facing": True,
            "location": "production",
            "revenue_at_risk": 5000000,
            "customers_affected": 50000,
        },
    )
    
    # Add risk assessment
    asset.risk_assessment = RiskAssessment(
        risk_level=RiskLevel.HIGH,
        regulation="EU AI Act",
        requirements=["human-oversight", "documentation", "testing"],
        assessed_at=datetime.utcnow(),
        assessed_by="test",
    )
    
    return asset


# ============================================================================
# Risk Score Calculation Tests
# ============================================================================

def test_calculate_risk_score_minimal(sample_minimal_asset):
    """Test risk score calculation for minimal risk asset."""
    registry = get_registry()
    registry.register(sample_minimal_asset)
    
    engine = get_risk_scoring_engine()
    score = engine.calculate_risk_score("minimal-001")
    
    assert score.asset_id == "minimal-001"
    assert score.score >= 0
    assert score.score < 20  # Should be minimal tier
    assert score.tier == RiskTier.MINIMAL
    assert RiskFactor.INHERENT in score.breakdown
    assert RiskFactor.DATA_SENSITIVITY in score.breakdown
    assert RiskFactor.OPERATIONAL_CONTEXT in score.breakdown
    assert RiskFactor.HISTORICAL in score.breakdown


def test_calculate_risk_score_high(sample_high_risk_asset):
    """Test risk score calculation for high risk asset."""
    registry = get_registry()
    registry.register(sample_high_risk_asset)
    
    engine = get_risk_scoring_engine()
    score = engine.calculate_risk_score("high-001")
    
    assert score.asset_id == "high-001"
    assert score.score >= 60  # Should be high tier
    assert score.score < 80
    assert score.tier == RiskTier.HIGH


def test_calculate_risk_score_critical(sample_critical_asset):
    """Test risk score calculation for critical risk asset."""
    registry = get_registry()
    registry.register(sample_critical_asset)
    
    engine = get_risk_scoring_engine()
    score = engine.calculate_risk_score("critical-001")
    
    assert score.asset_id == "critical-001"
    assert score.score >= 80  # Should be critical tier
    assert score.tier == RiskTier.CRITICAL


def test_calculate_risk_score_not_found():
    """Test risk score calculation for non-existent asset."""
    engine = get_risk_scoring_engine()
    
    with pytest.raises(ValueError, match="not found"):
        engine.calculate_risk_score("nonexistent")


# ============================================================================
# Risk Factor Tests
# ============================================================================

def test_inherent_risk_factor(sample_high_risk_asset):
    """Test inherent risk factor calculation."""
    registry = get_registry()
    registry.register(sample_high_risk_asset)
    
    engine = get_risk_scoring_engine()
    score = engine.calculate_risk_score("high-001")
    
    # High risk level should contribute 75 points
    assert score.breakdown[RiskFactor.INHERENT] == 75


def test_data_sensitivity_factor(sample_high_risk_asset):
    """Test data sensitivity factor calculation."""
    registry = get_registry()
    registry.register(sample_high_risk_asset)
    
    engine = get_risk_scoring_engine()
    score = engine.calculate_risk_score("high-001")
    
    # PHI tag should contribute 25 points
    assert score.breakdown[RiskFactor.DATA_SENSITIVITY] >= 25


def test_operational_context_factor(sample_high_risk_asset):
    """Test operational context factor calculation."""
    registry = get_registry()
    registry.register(sample_high_risk_asset)
    
    engine = get_risk_scoring_engine()
    score = engine.calculate_risk_score("high-001")
    
    # Production + user-facing + automated-decision should contribute
    assert score.breakdown[RiskFactor.OPERATIONAL_CONTEXT] > 0


def test_historical_risk_factor_no_incidents(sample_high_risk_asset):
    """Test historical risk factor with no incidents."""
    registry = get_registry()
    registry.register(sample_high_risk_asset)
    
    engine = get_risk_scoring_engine()
    score = engine.calculate_risk_score("high-001")
    
    # No incidents should contribute 0
    assert score.breakdown[RiskFactor.HISTORICAL] == 0


def test_historical_risk_factor_with_incidents(sample_high_risk_asset):
    """Test historical risk factor with incidents."""
    registry = get_registry()
    registry.register(sample_high_risk_asset)
    
    # Add incident event
    tracker = get_tracker()
    tracker.track_event(
        asset_id="high-001",
        event_type="incident",
        description="Security incident",
        metadata={"severity": "major"},
    )
    
    engine = get_risk_scoring_engine()
    score = engine.calculate_risk_score("high-001")
    
    # Incident should contribute to historical risk
    assert score.breakdown[RiskFactor.HISTORICAL] > 0


# ============================================================================
# Risk Tier Tests
# ============================================================================

def test_risk_tier_minimal():
    """Test risk tier determination for minimal risk."""
    engine = get_risk_scoring_engine()
    
    assert engine.get_risk_tier(0) == RiskTier.MINIMAL
    assert engine.get_risk_tier(10) == RiskTier.MINIMAL
    assert engine.get_risk_tier(19) == RiskTier.MINIMAL


def test_risk_tier_low():
    """Test risk tier determination for low risk."""
    engine = get_risk_scoring_engine()
    
    assert engine.get_risk_tier(20) == RiskTier.LOW
    assert engine.get_risk_tier(30) == RiskTier.LOW
    assert engine.get_risk_tier(39) == RiskTier.LOW


def test_risk_tier_medium():
    """Test risk tier determination for medium risk."""
    engine = get_risk_scoring_engine()
    
    assert engine.get_risk_tier(40) == RiskTier.MEDIUM
    assert engine.get_risk_tier(50) == RiskTier.MEDIUM
    assert engine.get_risk_tier(59) == RiskTier.MEDIUM


def test_risk_tier_high():
    """Test risk tier determination for high risk."""
    engine = get_risk_scoring_engine()
    
    assert engine.get_risk_tier(60) == RiskTier.HIGH
    assert engine.get_risk_tier(70) == RiskTier.HIGH
    assert engine.get_risk_tier(79) == RiskTier.HIGH


def test_risk_tier_critical():
    """Test risk tier determination for critical risk."""
    engine = get_risk_scoring_engine()
    
    assert engine.get_risk_tier(80) == RiskTier.CRITICAL
    assert engine.get_risk_tier(90) == RiskTier.CRITICAL
    assert engine.get_risk_tier(100) == RiskTier.CRITICAL


# ============================================================================
# Score Caching Tests
# ============================================================================

def test_get_score_cached(sample_high_risk_asset):
    """Test getting cached risk score."""
    registry = get_registry()
    registry.register(sample_high_risk_asset)
    
    engine = get_risk_scoring_engine()
    
    # Calculate score
    score1 = engine.calculate_risk_score("high-001")
    
    # Get cached score
    score2 = engine.get_score("high-001")
    
    assert score2 is not None
    assert score2.asset_id == score1.asset_id
    assert score2.score == score1.score


def test_get_score_not_calculated():
    """Test getting score when not calculated."""
    registry = get_registry()
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
    registry.register(asset)
    
    engine = get_risk_scoring_engine()
    
    # Should calculate on first get
    score = engine.get_score("test-001")
    assert score is not None


def test_score_expiration(sample_high_risk_asset):
    """Test score expiration and recalculation."""
    registry = get_registry()
    registry.register(sample_high_risk_asset)
    
    engine = get_risk_scoring_engine()
    
    # Calculate score
    score1 = engine.calculate_risk_score("high-001")
    
    # Manually expire score
    score1.expires_at = datetime.utcnow() - timedelta(days=1)
    
    # Get score should recalculate
    score2 = engine.get_score("high-001")
    
    assert score2.calculated_at > score1.calculated_at


# ============================================================================
# Bulk Operations Tests
# ============================================================================

def test_recalculate_all_scores(sample_minimal_asset, sample_high_risk_asset):
    """Test bulk recalculation of all scores."""
    registry = get_registry()
    registry.register(sample_minimal_asset)
    registry.register(sample_high_risk_asset)
    
    engine = get_risk_scoring_engine()
    scores = engine.recalculate_all_scores()
    
    assert len(scores) == 2
    assert any(s.asset_id == "minimal-001" for s in scores)
    assert any(s.asset_id == "high-001" for s in scores)


def test_get_risk_breakdown(sample_high_risk_asset):
    """Test getting detailed risk breakdown."""
    registry = get_registry()
    registry.register(sample_high_risk_asset)
    
    engine = get_risk_scoring_engine()
    breakdown = engine.get_risk_breakdown("high-001")
    
    assert RiskFactor.INHERENT in breakdown
    assert RiskFactor.DATA_SENSITIVITY in breakdown
    assert RiskFactor.OPERATIONAL_CONTEXT in breakdown
    assert RiskFactor.HISTORICAL in breakdown


# ============================================================================
# Edge Cases Tests
# ============================================================================

def test_asset_without_risk_assessment(sample_minimal_asset):
    """Test asset without risk assessment defaults to minimal."""
    registry = get_registry()
    registry.register(sample_minimal_asset)
    
    engine = get_risk_scoring_engine()
    score = engine.calculate_risk_score("minimal-001")
    
    # Should default to minimal inherent risk
    assert score.breakdown[RiskFactor.INHERENT] == 10


def test_asset_without_tags(sample_minimal_asset):
    """Test asset without tags has zero data sensitivity."""
    sample_minimal_asset.tags = []
    
    registry = get_registry()
    registry.register(sample_minimal_asset)
    
    engine = get_risk_scoring_engine()
    score = engine.calculate_risk_score("minimal-001")
    
    assert score.breakdown[RiskFactor.DATA_SENSITIVITY] == 0


def test_asset_without_metadata(sample_minimal_asset):
    """Test asset without metadata."""
    sample_minimal_asset.metadata = {}
    
    registry = get_registry()
    registry.register(sample_minimal_asset)
    
    engine = get_risk_scoring_engine()
    score = engine.calculate_risk_score("minimal-001")
    
    # Should still calculate score
    assert score.score >= 0


def test_score_normalization():
    """Test that scores are normalized to 0-100 range."""
    registry = get_registry()
    
    # Create asset with many high-risk tags
    asset = AIAsset(
        asset_id="test-001",
        asset_type=AssetType.AGENT,
        name="Test Agent",
        description="Test",
        owner="test",
        status=AssetStatus.ACTIVE,
        tags=["phi", "pii", "financial", "biometric", "sensitive"] * 10,  # Many tags
        metadata={},
    )
    registry.register(asset)
    
    engine = get_risk_scoring_engine()
    score = engine.calculate_risk_score("test-001")
    
    # Score should be capped at 100
    assert score.score <= 100.0
    assert score.score >= 0.0


def test_singleton_instance():
    """Test that risk scoring engine is a singleton."""
    engine1 = get_risk_scoring_engine()
    engine2 = get_risk_scoring_engine()
    
    assert engine1 is engine2
