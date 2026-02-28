"""
Risk Metrics Aggregation Engine for Omnipath V2.

This module aggregates risk data across the entire asset portfolio to provide
executive-level visibility into organizational risk posture.

Author: Dev Team Lead
Date: 2026-02-26
Built with Pride for Obex Blackvault
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Any, Optional
from collections import defaultdict

from ..registry.asset_registry import get_registry, AssetType, AssetStatus
from .risk_scoring import get_risk_scoring_engine, RiskTier


@dataclass
class RiskMetrics:
    """
    Aggregated risk metrics for the entire asset portfolio.
    
    Provides executive-level visibility into risk posture.
    """
    total_assets: int
    assets_by_type: Dict[str, int]  # AssetType → count
    assets_by_tier: Dict[str, int]  # RiskTier → count
    assets_by_status: Dict[str, int]  # AssetStatus → count
    average_risk_score: float
    median_risk_score: float
    risk_score_distribution: Dict[int, int]  # bucket (0-10, 10-20, ...) → count
    top_risks: List[Tuple[str, float, str]]  # (asset_id, score, tier)
    assets_requiring_approval: int
    compliance_coverage: float  # % of assets with risk assessments
    generated_at: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary."""
        return {
            "total_assets": self.total_assets,
            "assets_by_type": self.assets_by_type,
            "assets_by_tier": self.assets_by_tier,
            "assets_by_status": self.assets_by_status,
            "average_risk_score": round(self.average_risk_score, 2),
            "median_risk_score": round(self.median_risk_score, 2),
            "risk_score_distribution": self.risk_score_distribution,
            "top_risks": [
                {"asset_id": aid, "score": round(score, 2), "tier": tier}
                for aid, score, tier in self.top_risks
            ],
            "assets_requiring_approval": self.assets_requiring_approval,
            "compliance_coverage": round(self.compliance_coverage, 2),
            "generated_at": self.generated_at.isoformat(),
        }


@dataclass
class RiskHeatmap:
    """
    Risk heatmap showing asset type × risk tier matrix.
    
    Useful for visualizing risk distribution across asset types.
    """
    matrix: Dict[str, Dict[str, int]]  # AssetType → (RiskTier → count)
    row_totals: Dict[str, int]  # AssetType → total count
    column_totals: Dict[str, int]  # RiskTier → total count
    grand_total: int
    generated_at: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert heatmap to dictionary."""
        return {
            "matrix": self.matrix,
            "row_totals": self.row_totals,
            "column_totals": self.column_totals,
            "grand_total": self.grand_total,
            "generated_at": self.generated_at.isoformat(),
        }


class RiskMetricsAggregator:
    """
    Aggregates risk metrics across the entire asset portfolio.
    
    Provides portfolio-wide statistics, heatmaps, and insights.
    """
    
    def __init__(self):
        """Initialize the aggregator."""
        self.registry = get_registry()
        self.risk_engine = get_risk_scoring_engine()
    
    def get_portfolio_metrics(self) -> RiskMetrics:
        """
        Get comprehensive portfolio risk metrics.
        
        Returns:
            RiskMetrics with aggregated statistics
        """
        assets = self.registry.list_all()
        
        if not assets:
            return RiskMetrics(
                total_assets=0,
                assets_by_type={},
                assets_by_tier={},
                assets_by_status={},
                average_risk_score=0.0,
                median_risk_score=0.0,
                risk_score_distribution={},
                top_risks=[],
                assets_requiring_approval=0,
                compliance_coverage=0.0,
            )
        
        # Count by type
        assets_by_type = defaultdict(int)
        for asset in assets:
            assets_by_type[asset.asset_type.value] += 1
        
        # Count by status
        assets_by_status = defaultdict(int)
        for asset in assets:
            assets_by_status[asset.status.value] += 1
        
        # Calculate risk scores
        risk_scores = []
        assets_by_tier = defaultdict(int)
        assets_with_scores = 0
        
        for asset in assets:
            # Get or calculate risk score
            risk_score = self.risk_engine.get_score(asset.asset_id)
            if risk_score:
                risk_scores.append((asset.asset_id, risk_score.score, risk_score.tier))
                assets_by_tier[risk_score.tier.value] += 1
                assets_with_scores += 1
        
        # Calculate statistics
        if risk_scores:
            scores_only = [score for _, score, _ in risk_scores]
            average_score = sum(scores_only) / len(scores_only)
            median_score = sorted(scores_only)[len(scores_only) // 2]
            
            # Distribution (10-point buckets)
            distribution = defaultdict(int)
            for score in scores_only:
                bucket = int(score // 10) * 10
                distribution[bucket] += 1
            
            # Top risks (top 10)
            top_risks = sorted(risk_scores, key=lambda x: x[1], reverse=True)[:10]
            
            # Assets requiring approval (Medium and above)
            requiring_approval = sum(
                1 for _, _, tier in risk_scores
                if tier in [RiskTier.MEDIUM, RiskTier.HIGH, RiskTier.CRITICAL]
            )
        else:
            average_score = 0.0
            median_score = 0.0
            distribution = {}
            top_risks = []
            requiring_approval = 0
        
        # Compliance coverage
        compliance_coverage = (assets_with_scores / len(assets)) * 100 if assets else 0.0
        
        return RiskMetrics(
            total_assets=len(assets),
            assets_by_type=dict(assets_by_type),
            assets_by_tier=dict(assets_by_tier),
            assets_by_status=dict(assets_by_status),
            average_risk_score=average_score,
            median_risk_score=median_score,
            risk_score_distribution=dict(distribution),
            top_risks=top_risks,
            assets_requiring_approval=requiring_approval,
            compliance_coverage=compliance_coverage,
        )
    
    def get_risk_heatmap(self) -> RiskHeatmap:
        """
        Generate risk heatmap (asset type × risk tier matrix).
        
        Returns:
            RiskHeatmap with matrix data
        """
        assets = self.registry.list_all()
        
        # Initialize matrix
        matrix = defaultdict(lambda: defaultdict(int))
        row_totals = defaultdict(int)
        column_totals = defaultdict(int)
        
        # Populate matrix
        for asset in assets:
            asset_type = asset.asset_type.value
            
            # Get risk score
            risk_score = self.risk_engine.get_score(asset.asset_id)
            if risk_score:
                tier = risk_score.tier.value
            else:
                tier = "unknown"
            
            matrix[asset_type][tier] += 1
            row_totals[asset_type] += 1
            column_totals[tier] += 1
        
        # Convert to regular dicts
        matrix_dict = {k: dict(v) for k, v in matrix.items()}
        
        return RiskHeatmap(
            matrix=matrix_dict,
            row_totals=dict(row_totals),
            column_totals=dict(column_totals),
            grand_total=len(assets),
        )
    
    def get_top_risks(self, limit: int = 10) -> List[Tuple[str, float, str, str]]:
        """
        Get top N highest-risk assets.
        
        Args:
            limit: Maximum number of assets to return
            
        Returns:
            List of (asset_id, score, tier, asset_name) tuples
        """
        assets = self.registry.list_all()
        
        # Get risk scores
        risk_scores = []
        for asset in assets:
            risk_score = self.risk_engine.get_score(asset.asset_id)
            if risk_score:
                risk_scores.append((
                    asset.asset_id,
                    risk_score.score,
                    risk_score.tier.value,
                    asset.name,
                ))
        
        # Sort by score descending
        risk_scores.sort(key=lambda x: x[1], reverse=True)
        
        return risk_scores[:limit]
    
    def get_risk_distribution(self) -> Dict[str, int]:
        """
        Get risk tier distribution.
        
        Returns:
            Dictionary mapping tier names to counts
        """
        assets = self.registry.list_all()
        
        distribution = defaultdict(int)
        for asset in assets:
            risk_score = self.risk_engine.get_score(asset.asset_id)
            if risk_score:
                distribution[risk_score.tier.value] += 1
            else:
                distribution["unknown"] += 1
        
        return dict(distribution)
    
    def get_approval_queue_stats(self) -> Dict[str, Any]:
        """
        Get approval queue statistics.
        
        Returns:
            Dictionary with approval queue metrics
        """
        assets = self.registry.list_all()
        
        # Count assets by approval requirement
        no_approval = 0  # Minimal, Low
        operator_approval = 0  # Low
        admin_approval = 0  # Medium
        compliance_approval = 0  # High, Critical
        
        for asset in assets:
            risk_score = self.risk_engine.get_score(asset.asset_id)
            if risk_score:
                if risk_score.tier == RiskTier.MINIMAL:
                    no_approval += 1
                elif risk_score.tier == RiskTier.LOW:
                    operator_approval += 1
                elif risk_score.tier == RiskTier.MEDIUM:
                    admin_approval += 1
                elif risk_score.tier in [RiskTier.HIGH, RiskTier.CRITICAL]:
                    compliance_approval += 1
        
        return {
            "total_assets": len(assets),
            "no_approval_required": no_approval,
            "operator_approval_required": operator_approval,
            "admin_approval_required": admin_approval,
            "compliance_approval_required": compliance_approval,
            "total_requiring_approval": operator_approval + admin_approval + compliance_approval,
        }
    
    def get_compliance_posture(self) -> Dict[str, Any]:
        """
        Get compliance posture summary.
        
        Returns:
            Dictionary with compliance metrics
        """
        assets = self.registry.list_all()
        
        if not assets:
            return {
                "total_assets": 0,
                "assets_with_risk_assessment": 0,
                "assets_with_tags": 0,
                "coverage_percentage": 0.0,
                "compliance_ready": 0,
                "compliance_gaps": 0,
            }
        
        assets_with_risk_assessment = 0
        assets_with_tags = 0
        compliance_ready = 0
        
        for asset in assets:
            # An asset is considered "risk-assessed" when it has a calculated
            # risk_score (set by RiskScoringEngine.calculate_risk_score()).  The
            # legacy risk_assessment attribute (set by RegulatoryMapping) is a
            # separate concern and may not be present on all assets.
            has_risk_score = (
                hasattr(asset, 'risk_score') and asset.risk_score is not None
            )
            if has_risk_score:
                assets_with_risk_assessment += 1

            # Check tags
            if asset.tags:
                assets_with_tags += 1

            # Check if compliance ready (has both risk score and tags)
            if has_risk_score and asset.tags:
                compliance_ready += 1
        
        coverage = (assets_with_risk_assessment / len(assets)) * 100
        
        return {
            "total_assets": len(assets),
            "assets_with_risk_assessment": assets_with_risk_assessment,
            "assets_with_tags": assets_with_tags,
            "coverage_percentage": round(coverage, 2),
            "compliance_ready": compliance_ready,
            "compliance_gaps": len(assets) - compliance_ready,
        }
    
    def get_risk_trends(
        self,
        days: int = 30,
        granularity: str = "daily",
    ) -> List[Tuple[datetime, float, int]]:
        """
        Get risk score trends over time.

        Derives trend data from the ``calculated_at`` timestamps stored on each
        asset's ``risk_score`` attribute.  Scores are bucketed by *granularity*
        and averaged within each bucket.

        When fewer than two historical data-points are available (e.g. the
        registry is freshly populated and all scores were calculated in the
        same bucket) the method returns a single entry representing the current
        portfolio state so callers always receive a non-empty list.

        Args:
            days:        Number of days to look back (default 30).
            granularity: Bucket size — ``"daily"``, ``"weekly"``, or
                         ``"monthly"`` (default ``"daily"``).

        Returns:
            List of ``(bucket_timestamp, average_score, asset_count)`` tuples
            ordered from oldest to newest.
        """
        from collections import defaultdict

        # Validate granularity
        valid_granularities = {"daily", "weekly", "monthly"}
        if granularity not in valid_granularities:
            raise ValueError(
                f"granularity must be one of {valid_granularities}, got '{granularity}'"
            )

        now = datetime.utcnow()
        cutoff = now - timedelta(days=days)

        # Determine bucket size in days
        bucket_days = {"daily": 1, "weekly": 7, "monthly": 30}[granularity]

        # Collect (calculated_at, score) pairs from assets that have been scored
        assets = self.registry.list_all()
        data_points: List[Tuple[datetime, float]] = []

        for asset in assets:
            risk_score = self.risk_engine.get_score(asset.asset_id)
            if risk_score is None:
                continue
            ts = risk_score.calculated_at
            if ts >= cutoff:
                data_points.append((ts, risk_score.score))

        # If no historical data exists, return the current portfolio snapshot
        if not data_points:
            metrics = self.get_portfolio_metrics()
            return [(now, metrics.average_risk_score, metrics.total_assets)]

        # Bucket data points
        # Bucket key = number of complete bucket_days intervals since epoch
        epoch = datetime(1970, 1, 1)

        def _bucket_key(ts: datetime) -> int:
            return int((ts - epoch).days // bucket_days)

        def _bucket_start(key: int) -> datetime:
            return epoch + timedelta(days=key * bucket_days)

        buckets: Dict[int, List[float]] = defaultdict(list)
        for ts, score in data_points:
            buckets[_bucket_key(ts)].append(score)

        # Build the result list ordered from oldest to newest
        result: List[Tuple[datetime, float, int]] = []
        for key in sorted(buckets.keys()):
            scores = buckets[key]
            avg_score = sum(scores) / len(scores)
            result.append((_bucket_start(key), avg_score, len(scores)))

        return result


# Global instance
_aggregator = None


def get_risk_metrics_aggregator() -> RiskMetricsAggregator:
    """Get the global risk metrics aggregator instance."""
    global _aggregator
    if _aggregator is None:
        _aggregator = RiskMetricsAggregator()
    return _aggregator
