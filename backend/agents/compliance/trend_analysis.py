"""
Trend Analysis & Forecasting for Omnipath V2.

This module analyzes trends and forecasts future governance needs.

Author: Dev Team Lead
Date: 2026-02-26
Built with Pride for Obex Blackvault
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Any, Optional
from collections import defaultdict
import statistics

from ..registry.asset_registry import get_registry
from .risk_scoring import get_risk_scoring_engine, RiskTier


@dataclass
class TrendData:
    """
    Time series trend data with forecasting.

    Provides historical data, moving averages, velocity, and forecasts.
    """

    metric_name: str
    time_series: List[Tuple[datetime, float]]  # (timestamp, value)
    moving_average_7d: List[Tuple[datetime, float]]
    moving_average_30d: List[Tuple[datetime, float]]
    velocity: float  # Rate of change (units per day)
    forecast_30d: float
    forecast_60d: float
    forecast_90d: float
    confidence: float  # Forecast confidence (0-1)
    generated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert trend data to dictionary."""
        return {
            "metric_name": self.metric_name,
            "time_series": [
                {"timestamp": ts.isoformat(), "value": round(val, 2)}
                for ts, val in self.time_series
            ],
            "moving_average_7d": [
                {"timestamp": ts.isoformat(), "value": round(val, 2)}
                for ts, val in self.moving_average_7d
            ],
            "moving_average_30d": [
                {"timestamp": ts.isoformat(), "value": round(val, 2)}
                for ts, val in self.moving_average_30d
            ],
            "velocity": round(self.velocity, 4),
            "forecast": {
                "30_days": round(self.forecast_30d, 2),
                "60_days": round(self.forecast_60d, 2),
                "90_days": round(self.forecast_90d, 2),
            },
            "confidence": round(self.confidence, 2),
            "generated_at": self.generated_at.isoformat(),
        }


class TrendAnalyzer:
    """
    Analyzes trends and forecasts future governance needs.

    Tracks risk scores, asset growth, compliance posture, and approval volumes over time.
    """

    def __init__(self):
        """Initialize the analyzer."""
        self.registry = get_registry()
        self.risk_engine = get_risk_scoring_engine()

        # In-memory storage for historical data (in production, would use database)
        self._historical_risk_scores: Dict[str, List[Tuple[datetime, float]]] = defaultdict(list)
        self._historical_asset_counts: List[Tuple[datetime, int]] = []
        self._historical_approval_counts: List[Tuple[datetime, int]] = []

    def record_snapshot(self):
        """
        Record current state snapshot for trend analysis.

        Should be called periodically (e.g., daily) to build historical data.
        """
        now = datetime.utcnow()

        # Record asset count
        assets = self.registry.list_all()
        self._historical_asset_counts.append((now, len(assets)))

        # Record risk scores
        for asset in assets:
            risk_score = self.risk_engine.get_score(asset.asset_id)
            if risk_score:
                self._historical_risk_scores[asset.asset_id].append((now, risk_score.score))

    def get_risk_score_trends(self, days: int = 30, asset_id: Optional[str] = None) -> TrendData:
        """
        Get risk score trends over time.

        Args:
            days: Number of days to analyze
            asset_id: Specific asset ID (None for portfolio average)

        Returns:
            TrendData with risk score trends
        """
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=days)

        if asset_id:
            # Single asset trend
            time_series = [
                (ts, score)
                for ts, score in self._historical_risk_scores.get(asset_id, [])
                if ts >= start_time
            ]
            metric_name = f"risk_score_{asset_id}"
        else:
            # Portfolio average trend
            # Group by day and calculate average
            daily_averages = defaultdict(list)
            for asset_scores in self._historical_risk_scores.values():
                for ts, score in asset_scores:
                    if ts >= start_time:
                        day = ts.date()
                        daily_averages[day].append(score)

            time_series = [
                (datetime.combine(day, datetime.min.time()), statistics.mean(scores))
                for day, scores in sorted(daily_averages.items())
            ]
            metric_name = "portfolio_average_risk_score"

        # If no historical data, use current snapshot
        if not time_series:
            assets = self.registry.list_all()
            current_scores = []
            for asset in assets:
                risk_score = self.risk_engine.get_score(asset.asset_id)
                if risk_score:
                    current_scores.append(risk_score.score)

            if current_scores:
                avg_score = statistics.mean(current_scores)
                time_series = [(end_time, avg_score)]
            else:
                time_series = [(end_time, 0.0)]

        # Calculate moving averages
        ma_7d = self._calculate_moving_average(time_series, 7)
        ma_30d = self._calculate_moving_average(time_series, 30)

        # Calculate velocity (rate of change)
        velocity = self._calculate_velocity(time_series)

        # Forecast using simple linear regression
        forecast_30d, forecast_60d, forecast_90d, confidence = self._forecast(
            time_series, [30, 60, 90]
        )

        return TrendData(
            metric_name=metric_name,
            time_series=time_series,
            moving_average_7d=ma_7d,
            moving_average_30d=ma_30d,
            velocity=velocity,
            forecast_30d=forecast_30d,
            forecast_60d=forecast_60d,
            forecast_90d=forecast_90d,
            confidence=confidence,
        )

    def get_asset_growth_trends(self, days: int = 30) -> TrendData:
        """
        Get asset growth trends over time.

        Args:
            days: Number of days to analyze

        Returns:
            TrendData with asset count trends
        """
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=days)

        # Filter historical data
        time_series = [
            (ts, count) for ts, count in self._historical_asset_counts if ts >= start_time
        ]

        # If no historical data, use current count
        if not time_series:
            current_count = len(self.registry.list_all())
            time_series = [(end_time, current_count)]

        # Calculate moving averages
        ma_7d = self._calculate_moving_average(time_series, 7)
        ma_30d = self._calculate_moving_average(time_series, 30)

        # Calculate velocity
        velocity = self._calculate_velocity(time_series)

        # Forecast
        forecast_30d, forecast_60d, forecast_90d, confidence = self._forecast(
            time_series, [30, 60, 90]
        )

        return TrendData(
            metric_name="asset_count",
            time_series=time_series,
            moving_average_7d=ma_7d,
            moving_average_30d=ma_30d,
            velocity=velocity,
            forecast_30d=forecast_30d,
            forecast_60d=forecast_60d,
            forecast_90d=forecast_90d,
            confidence=confidence,
        )

    def get_compliance_trends(self, days: int = 30) -> TrendData:
        """
        Get compliance coverage trends over time.

        Args:
            days: Number of days to analyze

        Returns:
            TrendData with compliance coverage trends
        """
        # For now, return current compliance coverage
        # In production, would track historical compliance data
        assets = self.registry.list_all()
        assets_with_scores = sum(
            1 for asset in assets if self.risk_engine.get_score(asset.asset_id) is not None
        )

        coverage = (assets_with_scores / len(assets) * 100) if assets else 0.0

        end_time = datetime.utcnow()
        time_series = [(end_time, coverage)]

        return TrendData(
            metric_name="compliance_coverage",
            time_series=time_series,
            moving_average_7d=time_series,
            moving_average_30d=time_series,
            velocity=0.0,
            forecast_30d=coverage,
            forecast_60d=coverage,
            forecast_90d=coverage,
            confidence=0.5,  # Low confidence without historical data
        )

    def get_approval_volume_trends(self, days: int = 30) -> TrendData:
        """
        Get approval volume trends over time.

        Args:
            days: Number of days to analyze

        Returns:
            TrendData with approval volume trends
        """
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=days)

        # Filter historical data
        time_series = [
            (ts, count) for ts, count in self._historical_approval_counts if ts >= start_time
        ]

        # If no historical data, estimate from current state
        if not time_series:
            assets = self.registry.list_all()
            requiring_approval = sum(
                1
                for asset in assets
                if self.risk_engine.get_score(asset.asset_id)
                and self.risk_engine.get_score(asset.asset_id).tier
                in [RiskTier.MEDIUM, RiskTier.HIGH, RiskTier.CRITICAL]
            )
            time_series = [(end_time, requiring_approval)]

        # Calculate moving averages
        ma_7d = self._calculate_moving_average(time_series, 7)
        ma_30d = self._calculate_moving_average(time_series, 30)

        # Calculate velocity
        velocity = self._calculate_velocity(time_series)

        # Forecast
        forecast_30d, forecast_60d, forecast_90d, confidence = self._forecast(
            time_series, [30, 60, 90]
        )

        return TrendData(
            metric_name="approval_volume",
            time_series=time_series,
            moving_average_7d=ma_7d,
            moving_average_30d=ma_30d,
            velocity=velocity,
            forecast_30d=forecast_30d,
            forecast_60d=forecast_60d,
            forecast_90d=forecast_90d,
            confidence=confidence,
        )

    def _calculate_moving_average(
        self, time_series: List[Tuple[datetime, float]], window_days: int
    ) -> List[Tuple[datetime, float]]:
        """
        Calculate moving average over time series.

        Args:
            time_series: List of (timestamp, value) tuples
            window_days: Window size in days

        Returns:
            List of (timestamp, moving_average) tuples
        """
        if not time_series:
            return []

        result = []
        for i, (ts, _) in enumerate(time_series):
            # Get values within window
            window_start = ts - timedelta(days=window_days)
            window_values = [val for t, val in time_series if window_start <= t <= ts]

            if window_values:
                avg = statistics.mean(window_values)
                result.append((ts, avg))

        return result

    def _calculate_velocity(self, time_series: List[Tuple[datetime, float]]) -> float:
        """
        Calculate velocity (rate of change) from time series.

        Args:
            time_series: List of (timestamp, value) tuples

        Returns:
            Velocity in units per day
        """
        if len(time_series) < 2:
            return 0.0

        # Use first and last points
        first_ts, first_val = time_series[0]
        last_ts, last_val = time_series[-1]

        days = (last_ts - first_ts).total_seconds() / 86400
        if days == 0:
            return 0.0

        return (last_val - first_val) / days

    def _forecast(
        self, time_series: List[Tuple[datetime, float]], forecast_days: List[int]
    ) -> Tuple[float, float, float, float]:
        """
        Forecast future values using simple linear regression.

        Args:
            time_series: List of (timestamp, value) tuples
            forecast_days: List of days to forecast (e.g., [30, 60, 90])

        Returns:
            Tuple of (forecast_30d, forecast_60d, forecast_90d, confidence)
        """
        if len(time_series) < 2:
            # Not enough data for forecast
            current_val = time_series[0][1] if time_series else 0.0
            return (current_val, current_val, current_val, 0.0)

        # Simple linear regression
        # Convert timestamps to days from start
        start_ts = time_series[0][0]
        x_values = [(ts - start_ts).total_seconds() / 86400 for ts, _ in time_series]
        y_values = [val for _, val in time_series]

        # Calculate slope and intercept
        len(x_values)
        x_mean = statistics.mean(x_values)
        y_mean = statistics.mean(y_values)

        numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values))
        denominator = sum((x - x_mean) ** 2 for x in x_values)

        if denominator == 0:
            slope = 0.0
        else:
            slope = numerator / denominator

        intercept = y_mean - slope * x_mean

        # Forecast
        last_x = x_values[-1]
        forecasts = []
        for days in forecast_days:
            future_x = last_x + days
            forecast_val = slope * future_x + intercept
            forecasts.append(max(0.0, forecast_val))  # Don't forecast negative values

        # Calculate confidence based on R²
        y_pred = [slope * x + intercept for x in x_values]
        ss_res = sum((y - y_p) ** 2 for y, y_p in zip(y_values, y_pred))
        ss_tot = sum((y - y_mean) ** 2 for y in y_values)

        if ss_tot == 0:
            r_squared = 0.0
        else:
            r_squared = 1 - (ss_res / ss_tot)

        confidence = max(0.0, min(1.0, r_squared))

        return (forecasts[0], forecasts[1], forecasts[2], confidence)


# Global instance
_analyzer = None


def get_trend_analyzer() -> TrendAnalyzer:
    """Get the global trend analyzer instance."""
    global _analyzer
    if _analyzer is None:
        _analyzer = TrendAnalyzer()
    return _analyzer
