"""
Tests for Trend Analysis & Forecasting.

Author: Dev Team Lead
Date: 2026-02-26
Built with Pride for Obex Blackvault
"""

import pytest
from datetime import datetime, timedelta

from backend.agents.compliance.trend_analysis import (
    get_trend_analyzer,
    TrendData,
)
from backend.agents.compliance.risk_scoring import get_risk_scoring_engine
from backend.agents.registry.asset_registry import (
    get_registry,
    AIAsset,
    AssetType,
    AssetStatus,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def clear_state():
    """Clear all state before each test."""
    registry = get_registry()
    registry.clear()

    # Clear trend analyzer state
    analyzer = get_trend_analyzer()
    analyzer._historical_risk_scores.clear()
    analyzer._historical_asset_counts.clear()
    analyzer._historical_approval_counts.clear()

    yield

    registry.clear()
    analyzer._historical_risk_scores.clear()
    analyzer._historical_asset_counts.clear()
    analyzer._historical_approval_counts.clear()


# ============================================================================
# Risk Score Trends Tests
# ============================================================================


def test_get_risk_score_trends_no_history():
    """Test risk score trends with no historical data."""
    registry = get_registry()
    risk_engine = get_risk_scoring_engine()

    # Create asset
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

    # Get trends
    analyzer = get_trend_analyzer()
    trends = analyzer.get_risk_score_trends(days=30)

    assert trends.metric_name == "portfolio_average_risk_score"
    assert len(trends.time_series) > 0
    assert trends.forecast_30d >= 0


def test_get_risk_score_trends_with_history():
    """Test risk score trends with historical snapshots."""
    registry = get_registry()
    risk_engine = get_risk_scoring_engine()
    analyzer = get_trend_analyzer()

    # Create asset
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

    # Record multiple snapshots
    for i in range(5):
        analyzer.record_snapshot()

    # Get trends
    trends = analyzer.get_risk_score_trends(days=30)

    assert len(trends.time_series) >= 1
    assert trends.velocity is not None


def test_get_risk_score_trends_specific_asset():
    """Test risk score trends for specific asset."""
    registry = get_registry()
    risk_engine = get_risk_scoring_engine()
    analyzer = get_trend_analyzer()

    # Create asset
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

    # Record snapshot
    analyzer.record_snapshot()

    # Get trends for specific asset
    trends = analyzer.get_risk_score_trends(days=30, asset_id="agent-001")

    assert trends.metric_name == "risk_score_agent-001"


# ============================================================================
# Asset Growth Trends Tests
# ============================================================================


def test_get_asset_growth_trends_no_history():
    """Test asset growth trends with no historical data."""
    registry = get_registry()

    # Create asset
    agent = AIAsset(
        asset_id="agent-001",
        asset_type=AssetType.AGENT,
        name="Test Agent",
        description="Test",
        owner="test",
        status=AssetStatus.ACTIVE,
        tags=[],
        metadata={},
    )
    registry.register(agent)

    # Get trends
    analyzer = get_trend_analyzer()
    trends = analyzer.get_asset_growth_trends(days=30)

    assert trends.metric_name == "asset_count"
    assert len(trends.time_series) > 0
    assert trends.time_series[0][1] == 1  # One asset


def test_get_asset_growth_trends_with_history():
    """Test asset growth trends with historical snapshots."""
    registry = get_registry()
    analyzer = get_trend_analyzer()

    # Record initial snapshot
    analyzer.record_snapshot()

    # Add assets over time
    for i in range(3):
        asset = AIAsset(
            asset_id=f"agent-{i:03d}",
            asset_type=AssetType.AGENT,
            name=f"Agent {i}",
            description="Test",
            owner="test",
            status=AssetStatus.ACTIVE,
            tags=[],
            metadata={},
        )
        registry.register(asset)
        analyzer.record_snapshot()

    # Get trends
    trends = analyzer.get_asset_growth_trends(days=30)

    assert len(trends.time_series) >= 2
    # Should show growth
    assert trends.velocity >= 0


# ============================================================================
# Compliance Trends Tests
# ============================================================================


def test_get_compliance_trends():
    """Test compliance coverage trends."""
    registry = get_registry()
    risk_engine = get_risk_scoring_engine()

    # Create assets with risk assessments
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

    # Get trends
    analyzer = get_trend_analyzer()
    trends = analyzer.get_compliance_trends(days=30)

    assert trends.metric_name == "compliance_coverage"
    assert len(trends.time_series) > 0
    assert 0 <= trends.time_series[0][1] <= 100


# ============================================================================
# Approval Volume Trends Tests
# ============================================================================


def test_get_approval_volume_trends():
    """Test approval volume trends."""
    registry = get_registry()
    risk_engine = get_risk_scoring_engine()

    # Create high-risk asset requiring approval
    agent = AIAsset(
        asset_id="agent-001",
        asset_type=AssetType.AGENT,
        name="High Risk Agent",
        description="Test",
        owner="test",
        status=AssetStatus.ACTIVE,
        tags=["phi", "automated-decision"],
        metadata={"location": "production"},
    )
    registry.register(agent)
    risk_engine.calculate_risk_score(agent.asset_id)

    # Get trends
    analyzer = get_trend_analyzer()
    trends = analyzer.get_approval_volume_trends(days=30)

    assert trends.metric_name == "approval_volume"
    assert len(trends.time_series) > 0


# ============================================================================
# Moving Average Tests
# ============================================================================


def test_calculate_moving_average():
    """Test moving average calculation."""
    analyzer = get_trend_analyzer()

    # Create time series
    now = datetime.utcnow()
    time_series = [(now - timedelta(days=i), 10.0 + i) for i in range(10, 0, -1)]

    # Calculate 3-day moving average
    ma = analyzer._calculate_moving_average(time_series, 3)

    assert len(ma) > 0
    # Each point should be average of window
    for ts, avg in ma:
        assert avg >= 10.0


def test_calculate_moving_average_empty():
    """Test moving average with empty time series."""
    analyzer = get_trend_analyzer()
    ma = analyzer._calculate_moving_average([], 7)
    assert len(ma) == 0


# ============================================================================
# Velocity Tests
# ============================================================================


def test_calculate_velocity_increasing():
    """Test velocity calculation for increasing trend."""
    analyzer = get_trend_analyzer()

    # Create increasing time series
    now = datetime.utcnow()
    time_series = [
        (now - timedelta(days=10), 10.0),
        (now, 20.0),
    ]

    velocity = analyzer._calculate_velocity(time_series)

    assert velocity > 0  # Positive velocity for increasing trend


def test_calculate_velocity_decreasing():
    """Test velocity calculation for decreasing trend."""
    analyzer = get_trend_analyzer()

    # Create decreasing time series
    now = datetime.utcnow()
    time_series = [
        (now - timedelta(days=10), 20.0),
        (now, 10.0),
    ]

    velocity = analyzer._calculate_velocity(time_series)

    assert velocity < 0  # Negative velocity for decreasing trend


def test_calculate_velocity_single_point():
    """Test velocity with single data point."""
    analyzer = get_trend_analyzer()

    time_series = [(datetime.utcnow(), 10.0)]
    velocity = analyzer._calculate_velocity(time_series)

    assert velocity == 0.0


# ============================================================================
# Forecasting Tests
# ============================================================================


def test_forecast_linear_trend():
    """Test forecasting with linear trend."""
    analyzer = get_trend_analyzer()

    # Create linear increasing time series.
    # range(30, 0, -1) produces i=30,29,...,1 so (now-30d, 40), ..., (now-1d, 11)
    # which is DECREASING.  We need an increasing series: oldest point has the
    # lowest value and the most recent point has the highest value.
    now = datetime.utcnow()
    time_series = [(now - timedelta(days=30 - i), 10.0 + i) for i in range(30)]

    forecast_30d, forecast_60d, forecast_90d, confidence = analyzer._forecast(
        time_series, [30, 60, 90]
    )

    # Should forecast continued growth
    assert forecast_30d >= time_series[-1][1]
    assert forecast_60d >= forecast_30d
    assert forecast_90d >= forecast_60d
    assert 0 <= confidence <= 1


def test_forecast_no_data():
    """Test forecasting with no data."""
    analyzer = get_trend_analyzer()

    forecast_30d, forecast_60d, forecast_90d, confidence = analyzer._forecast(
        [], [30, 60, 90]
    )

    assert forecast_30d == 0.0
    assert forecast_60d == 0.0
    assert forecast_90d == 0.0
    assert confidence == 0.0


def test_forecast_single_point():
    """Test forecasting with single data point."""
    analyzer = get_trend_analyzer()

    time_series = [(datetime.utcnow(), 50.0)]
    forecast_30d, forecast_60d, forecast_90d, confidence = analyzer._forecast(
        time_series, [30, 60, 90]
    )

    # Should return current value
    assert forecast_30d == 50.0
    assert forecast_60d == 50.0
    assert forecast_90d == 50.0


# ============================================================================
# Serialization Tests
# ============================================================================


def test_trend_data_to_dict():
    """Test TrendData serialization."""
    now = datetime.utcnow()
    trend = TrendData(
        metric_name="test_metric",
        time_series=[(now, 10.0), (now, 20.0)],
        moving_average_7d=[(now, 15.0)],
        moving_average_30d=[(now, 15.0)],
        velocity=1.0,
        forecast_30d=25.0,
        forecast_60d=30.0,
        forecast_90d=35.0,
        confidence=0.85,
    )

    data = trend.to_dict()

    assert data["metric_name"] == "test_metric"
    assert len(data["time_series"]) == 2
    assert data["velocity"] == 1.0
    assert data["forecast"]["30_days"] == 25.0
    assert data["confidence"] == 0.85
    assert "generated_at" in data


# ============================================================================
# Snapshot Recording Tests
# ============================================================================


def test_record_snapshot():
    """Test snapshot recording."""
    registry = get_registry()
    risk_engine = get_risk_scoring_engine()
    analyzer = get_trend_analyzer()

    # Create asset
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

    # Record snapshot
    analyzer.record_snapshot()

    # Check that data was recorded
    assert len(analyzer._historical_asset_counts) > 0
    assert len(analyzer._historical_risk_scores) > 0
