"""
Tests for Risk Metrics Aggregation.

Author: Dev Team Lead
Date: 2026-02-26
Built with Pride for Obex Blackvault
"""

import pytest
from datetime import datetime

from backend.agents.compliance.risk_metrics import (
    get_risk_metrics_aggregator,
    RiskMetrics,
    RiskHeatmap,
)
from backend.agents.compliance.risk_scoring import get_risk_scoring_engine, RiskTier
from backend.agents.registry.asset_registry import get_registry, AIAsset, AssetType, AssetStatus


@pytest.fixture(autouse=True)
def clear_state():
    """Clear all state before each test."""
    registry = get_registry()
    registry.clear()
    
    yield
    
    registry.clear()


# ============================================================================
# Portfolio Metrics Tests
# ============================================================================

def test_get_portfolio_metrics_empty():
    """Test portfolio metrics with no assets."""
    aggregator = get_risk_metrics_aggregator()
    metrics = aggregator.get_portfolio_metrics()
    
    assert metrics.total_assets == 0
    assert metrics.average_risk_score == 0.0
    assert metrics.compliance_coverage == 0.0


def test_get_portfolio_metrics_with_assets():
    """Test portfolio metrics with multiple assets."""
    registry = get_registry()
    risk_engine = get_risk_scoring_engine()
    
    # Register assets
    agent = AIAsset(
        asset_id="agent-001",
        asset_type=AssetType.AGENT,
        name="Test Agent",
        description="Test",
        owner="test",
        status=AssetStatus.ACTIVE,
        tags=["pii"],
        metadata={"risk_level": "high"},
    )
    registry.register(agent)
    
    tool = AIAsset(
        asset_id="tool-001",
        asset_type=AssetType.TOOL,
        name="Test Tool",
        description="Test",
        owner="test",
        status=AssetStatus.ACTIVE,
        tags=[],
        metadata={},
    )
    registry.register(tool)
    
    # Calculate risk scores
    risk_engine.calculate_risk_score(agent.asset_id)
    risk_engine.calculate_risk_score(tool.asset_id)
    
    # Get metrics
    aggregator = get_risk_metrics_aggregator()
    metrics = aggregator.get_portfolio_metrics()
    
    assert metrics.total_assets == 2
    assert metrics.average_risk_score > 0
    assert metrics.compliance_coverage == 100.0
    assert AssetType.AGENT.value in metrics.assets_by_type
    assert AssetType.TOOL.value in metrics.assets_by_type


def test_portfolio_metrics_risk_distribution():
    """Test risk tier distribution in portfolio metrics."""
    registry = get_registry()
    risk_engine = get_risk_scoring_engine()
    
    # Create high-risk asset
    high_risk = AIAsset(
        asset_id="high-001",
        asset_type=AssetType.AGENT,
        name="High Risk Agent",
        description="Test",
        owner="test",
        status=AssetStatus.ACTIVE,
        tags=["phi", "automated-decision"],
        metadata={"location": "production"},
    )
    registry.register(high_risk)
    risk_engine.calculate_risk_score(high_risk.asset_id)
    
    # Create low-risk asset
    low_risk = AIAsset(
        asset_id="low-001",
        asset_type=AssetType.TOOL,
        name="Low Risk Tool",
        description="Test",
        owner="test",
        status=AssetStatus.ACTIVE,
        tags=[],
        metadata={},
    )
    registry.register(low_risk)
    risk_engine.calculate_risk_score(low_risk.asset_id)
    
    # Get metrics
    aggregator = get_risk_metrics_aggregator()
    metrics = aggregator.get_portfolio_metrics()
    
    assert len(metrics.assets_by_tier) > 0
    assert sum(metrics.assets_by_tier.values()) == 2


def test_portfolio_metrics_top_risks():
    """Test top risks identification."""
    registry = get_registry()
    risk_engine = get_risk_scoring_engine()
    
    # Create multiple assets with different risk levels
    for i in range(5):
        asset = AIAsset(
            asset_id=f"asset-{i:03d}",
            asset_type=AssetType.AGENT,
            name=f"Agent {i}",
            description="Test",
            owner="test",
            status=AssetStatus.ACTIVE,
            tags=["pii"] if i < 2 else [],
            metadata={"location": "production"} if i < 3 else {},
        )
        registry.register(asset)
        risk_engine.calculate_risk_score(asset.asset_id)
    
    # Get metrics
    aggregator = get_risk_metrics_aggregator()
    metrics = aggregator.get_portfolio_metrics()
    
    assert len(metrics.top_risks) <= 5
    # Top risks should be sorted by score descending
    if len(metrics.top_risks) > 1:
        for i in range(len(metrics.top_risks) - 1):
            assert metrics.top_risks[i][1] >= metrics.top_risks[i+1][1]


# ============================================================================
# Risk Heatmap Tests
# ============================================================================

def test_get_risk_heatmap_empty():
    """Test risk heatmap with no assets."""
    aggregator = get_risk_metrics_aggregator()
    heatmap = aggregator.get_risk_heatmap()
    
    assert heatmap.grand_total == 0
    assert len(heatmap.matrix) == 0


def test_get_risk_heatmap_with_assets():
    """Test risk heatmap with multiple asset types."""
    registry = get_registry()
    risk_engine = get_risk_scoring_engine()
    
    # Create assets of different types
    agent = AIAsset(
        asset_id="agent-001",
        asset_type=AssetType.AGENT,
        name="Test Agent",
        description="Test",
        owner="test",
        status=AssetStatus.ACTIVE,
        tags=["pii"],
        metadata={},
    )
    registry.register(agent)
    risk_engine.calculate_risk_score(agent.asset_id)
    
    tool = AIAsset(
        asset_id="tool-001",
        asset_type=AssetType.TOOL,
        name="Test Tool",
        description="Test",
        owner="test",
        status=AssetStatus.ACTIVE,
        tags=[],
        metadata={},
    )
    registry.register(tool)
    risk_engine.calculate_risk_score(tool.asset_id)
    
    # Get heatmap
    aggregator = get_risk_metrics_aggregator()
    heatmap = aggregator.get_risk_heatmap()
    
    assert heatmap.grand_total == 2
    assert AssetType.AGENT.value in heatmap.matrix
    assert AssetType.TOOL.value in heatmap.matrix
    assert sum(heatmap.row_totals.values()) == 2


# ============================================================================
# Top Risks Tests
# ============================================================================

def test_get_top_risks_limit():
    """Test top risks with limit parameter."""
    registry = get_registry()
    risk_engine = get_risk_scoring_engine()
    
    # Create 15 assets
    for i in range(15):
        asset = AIAsset(
            asset_id=f"asset-{i:03d}",
            asset_type=AssetType.AGENT,
            name=f"Agent {i}",
            description="Test",
            owner="test",
            status=AssetStatus.ACTIVE,
            tags=["pii"] if i % 2 == 0 else [],
            metadata={},
        )
        registry.register(asset)
        risk_engine.calculate_risk_score(asset.asset_id)
    
    # Get top 5 risks
    aggregator = get_risk_metrics_aggregator()
    top_risks = aggregator.get_top_risks(limit=5)
    
    assert len(top_risks) == 5
    # Should be sorted by score descending
    for i in range(len(top_risks) - 1):
        assert top_risks[i][1] >= top_risks[i+1][1]


# ============================================================================
# Approval Queue Tests
# ============================================================================

def test_get_approval_queue_stats():
    """Test approval queue statistics."""
    registry = get_registry()
    risk_engine = get_risk_scoring_engine()
    
    # Create assets with different risk levels
    minimal = AIAsset(
        asset_id="minimal-001",
        asset_type=AssetType.TOOL,
        name="Minimal Risk",
        description="Test",
        owner="test",
        status=AssetStatus.ACTIVE,
        tags=[],
        metadata={},
    )
    registry.register(minimal)
    risk_engine.calculate_risk_score(minimal.asset_id)
    
    high = AIAsset(
        asset_id="high-001",
        asset_type=AssetType.AGENT,
        name="High Risk",
        description="Test",
        owner="test",
        status=AssetStatus.ACTIVE,
        tags=["phi", "automated-decision"],
        metadata={"location": "production"},
    )
    registry.register(high)
    risk_engine.calculate_risk_score(high.asset_id)
    
    # Get approval queue stats
    aggregator = get_risk_metrics_aggregator()
    stats = aggregator.get_approval_queue_stats()
    
    assert stats["total_assets"] == 2
    assert "no_approval_required" in stats
    assert "compliance_approval_required" in stats


# ============================================================================
# Compliance Posture Tests
# ============================================================================

def test_get_compliance_posture():
    """Test compliance posture summary."""
    registry = get_registry()
    risk_engine = get_risk_scoring_engine()
    
    # Create assets with and without risk assessments
    with_assessment = AIAsset(
        asset_id="assessed-001",
        asset_type=AssetType.AGENT,
        name="Assessed Agent",
        description="Test",
        owner="test",
        status=AssetStatus.ACTIVE,
        tags=["pii"],
        metadata={},
    )
    registry.register(with_assessment)
    risk_engine.calculate_risk_score(with_assessment.asset_id)
    
    without_assessment = AIAsset(
        asset_id="unassessed-001",
        asset_type=AssetType.TOOL,
        name="Unassessed Tool",
        description="Test",
        owner="test",
        status=AssetStatus.ACTIVE,
        tags=[],
        metadata={},
    )
    registry.register(without_assessment)
    
    # Get compliance posture
    aggregator = get_risk_metrics_aggregator()
    posture = aggregator.get_compliance_posture()
    
    assert posture["total_assets"] == 2
    assert posture["assets_with_risk_assessment"] == 1
    assert posture["coverage_percentage"] == 50.0
    assert posture["compliance_gaps"] == 1


# ============================================================================
# Serialization Tests
# ============================================================================

def test_risk_metrics_to_dict():
    """Test RiskMetrics serialization."""
    metrics = RiskMetrics(
        total_assets=10,
        assets_by_type={AssetType.AGENT.value: 5, AssetType.TOOL.value: 5},
        assets_by_tier={RiskTier.LOW.value: 8, RiskTier.HIGH.value: 2},
        assets_by_status={AssetStatus.ACTIVE.value: 10},
        average_risk_score=35.5,
        median_risk_score=30.0,
        risk_score_distribution={0: 2, 10: 3, 20: 3, 30: 2},
        top_risks=[("asset-001", 75.0, RiskTier.HIGH.value)],
        assets_requiring_approval=2,
        compliance_coverage=90.0,
    )
    
    data = metrics.to_dict()
    
    assert data["total_assets"] == 10
    assert data["average_risk_score"] == 35.5
    assert data["compliance_coverage"] == 90.0
    assert "generated_at" in data


def test_risk_heatmap_to_dict():
    """Test RiskHeatmap serialization."""
    heatmap = RiskHeatmap(
        matrix={
            AssetType.AGENT.value: {RiskTier.HIGH.value: 2, RiskTier.LOW.value: 3},
            AssetType.TOOL.value: {RiskTier.LOW.value: 5},
        },
        row_totals={AssetType.AGENT.value: 5, AssetType.TOOL.value: 5},
        column_totals={RiskTier.HIGH.value: 2, RiskTier.LOW.value: 8},
        grand_total=10,
    )
    
    data = heatmap.to_dict()
    
    assert data["grand_total"] == 10
    assert AssetType.AGENT.value in data["matrix"]
    assert "generated_at" in data
