"""
Dashboard API Routes for Omnipath V2.

Provides executive-level visibility into governance posture, risk landscape,
and compliance status.

Author: Dev Team Lead
Date: 2026-02-26
Built with Pride for Obex Blackvault
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Dict, List, Any, Optional
from datetime import datetime

from backend.agents.compliance.risk_metrics import get_risk_metrics_aggregator
from backend.agents.compliance.compliance_reporting import (
    get_compliance_reporter,
)
from backend.agents.compliance.trend_analysis import get_trend_analyzer


router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


# ============================================================================
# Risk Metrics Endpoints
# ============================================================================


@router.get("/metrics/overview")
async def get_metrics_overview() -> Dict[str, Any]:
    """
    Get portfolio overview metrics.

    Returns comprehensive statistics including asset counts, risk distribution,
    and compliance coverage.
    """
    aggregator = get_risk_metrics_aggregator()
    metrics = aggregator.get_portfolio_metrics()
    return metrics.to_dict()


@router.get("/metrics/risk-distribution")
async def get_risk_distribution() -> Dict[str, int]:
    """
    Get risk tier distribution.

    Returns count of assets in each risk tier.
    """
    aggregator = get_risk_metrics_aggregator()
    return aggregator.get_risk_distribution()


@router.get("/metrics/heatmap")
async def get_risk_heatmap() -> Dict[str, Any]:
    """
    Get risk heatmap (asset type × risk tier matrix).

    Returns matrix showing distribution of risk across asset types.
    """
    aggregator = get_risk_metrics_aggregator()
    heatmap = aggregator.get_risk_heatmap()
    return heatmap.to_dict()


@router.get("/metrics/top-risks")
async def get_top_risks(
    limit: int = Query(10, ge=1, le=100, description="Number of top risks to return")
) -> List[Dict[str, Any]]:
    """
    Get top N highest-risk assets.

    Args:
        limit: Maximum number of assets to return (1-100)

    Returns:
        List of highest-risk assets with scores and details
    """
    aggregator = get_risk_metrics_aggregator()
    top_risks = aggregator.get_top_risks(limit=limit)

    return [
        {
            "asset_id": asset_id,
            "score": round(score, 2),
            "tier": tier,
            "name": name,
        }
        for asset_id, score, tier, name in top_risks
    ]


@router.get("/metrics/approval-queue")
async def get_approval_queue_stats() -> Dict[str, Any]:
    """
    Get approval queue statistics.

    Returns counts of assets requiring different approval levels.
    """
    aggregator = get_risk_metrics_aggregator()
    return aggregator.get_approval_queue_stats()


@router.get("/metrics/trends")
async def get_risk_trends(
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze")
) -> Dict[str, Any]:
    """
    Get risk trends over time.

    Args:
        days: Number of days to look back (1-365)

    Returns:
        Risk score trends with moving averages
    """
    analyzer = get_trend_analyzer()
    trends = analyzer.get_risk_score_trends(days=days)
    return trends.to_dict()


@router.get("/metrics/compliance-posture")
async def get_compliance_posture() -> Dict[str, Any]:
    """
    Get compliance posture summary.

    Returns compliance coverage, gaps, and readiness metrics.
    """
    aggregator = get_risk_metrics_aggregator()
    return aggregator.get_compliance_posture()


# ============================================================================
# Compliance Reports Endpoints
# ============================================================================


@router.get("/reports/executive-summary")
async def get_executive_summary(
    days: int = Query(30, ge=1, le=365, description="Report period in days"),
    generated_by: str = Query("system", description="User ID generating report"),
) -> Dict[str, Any]:
    """
    Generate executive summary report.

    High-level overview of compliance posture, risk distribution, and key gaps.

    Args:
        days: Number of days to include in report (1-365)
        generated_by: User ID generating the report

    Returns:
        Executive summary report
    """
    reporter = get_compliance_reporter()
    report = reporter.generate_executive_summary(generated_by=generated_by, days=days)
    return report.to_dict()


@router.get("/reports/audit")
async def get_detailed_audit(
    days: int = Query(90, ge=1, le=365, description="Audit period in days"),
    generated_by: str = Query("system", description="User ID generating report"),
) -> Dict[str, Any]:
    """
    Generate detailed audit report.

    Complete asset inventory with compliance status, approval history,
    lineage tracking, and tag application history.

    Args:
        days: Number of days to include in audit (1-365)
        generated_by: User ID generating the report

    Returns:
        Detailed audit report
    """
    reporter = get_compliance_reporter()
    report = reporter.generate_detailed_audit(generated_by=generated_by, days=days)
    return report.to_dict()


@router.get("/reports/regulatory/{regulation}")
async def get_regulatory_compliance_report(
    regulation: str,
    generated_by: str = Query("system", description="User ID generating report"),
) -> Dict[str, Any]:
    """
    Generate regulatory compliance report.

    Compliance status for specific regulation (EU AI Act, GDPR, HIPAA, SOX).

    Args:
        regulation: Regulation name ("eu_ai_act", "gdpr", "hipaa", "sox")
        generated_by: User ID generating the report

    Returns:
        Regulatory compliance report
    """
    valid_regulations = ["eu_ai_act", "gdpr", "hipaa", "sox"]
    if regulation not in valid_regulations:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid regulation. Must be one of: {', '.join(valid_regulations)}",
        )

    reporter = get_compliance_reporter()
    report = reporter.generate_regulatory_compliance_report(
        regulation=regulation, generated_by=generated_by
    )
    return report.to_dict()


@router.get("/reports/risk-assessment")
async def get_risk_assessment_report(
    generated_by: str = Query("system", description="User ID generating report")
) -> Dict[str, Any]:
    """
    Generate risk assessment report.

    Portfolio risk analysis with factor breakdown, high-risk deep dive,
    and mitigation recommendations.

    Args:
        generated_by: User ID generating the report

    Returns:
        Risk assessment report
    """
    reporter = get_compliance_reporter()
    report = reporter.generate_risk_assessment_report(generated_by=generated_by)
    return report.to_dict()


# ============================================================================
# Trend Analysis Endpoints
# ============================================================================


@router.get("/trends/risk-scores")
async def get_risk_score_trends(
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze"),
    asset_id: Optional[str] = Query(
        None, description="Specific asset ID (None for portfolio)"
    ),
) -> Dict[str, Any]:
    """
    Get risk score trends over time.

    Args:
        days: Number of days to analyze (1-365)
        asset_id: Specific asset ID (None for portfolio average)

    Returns:
        Risk score trends with forecasts
    """
    analyzer = get_trend_analyzer()
    trends = analyzer.get_risk_score_trends(days=days, asset_id=asset_id)
    return trends.to_dict()


@router.get("/trends/asset-growth")
async def get_asset_growth_trends(
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze")
) -> Dict[str, Any]:
    """
    Get asset growth trends over time.

    Args:
        days: Number of days to analyze (1-365)

    Returns:
        Asset count trends with forecasts
    """
    analyzer = get_trend_analyzer()
    trends = analyzer.get_asset_growth_trends(days=days)
    return trends.to_dict()


@router.get("/trends/compliance")
async def get_compliance_trends(
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze")
) -> Dict[str, Any]:
    """
    Get compliance coverage trends over time.

    Args:
        days: Number of days to analyze (1-365)

    Returns:
        Compliance coverage trends with forecasts
    """
    analyzer = get_trend_analyzer()
    trends = analyzer.get_compliance_trends(days=days)
    return trends.to_dict()


@router.get("/trends/approval-volume")
async def get_approval_volume_trends(
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze")
) -> Dict[str, Any]:
    """
    Get approval volume trends over time.

    Args:
        days: Number of days to analyze (1-365)

    Returns:
        Approval volume trends with forecasts
    """
    analyzer = get_trend_analyzer()
    trends = analyzer.get_approval_volume_trends(days=days)
    return trends.to_dict()


@router.get("/forecast/{metric}")
async def get_forecast(
    metric: str,
    days: int = Query(
        30, ge=1, le=365, description="Historical days to base forecast on"
    ),
) -> Dict[str, Any]:
    """
    Get forecast for specific metric.

    Args:
        metric: Metric name ("risk_score", "asset_count", "compliance", "approval_volume")
        days: Number of historical days to analyze (1-365)

    Returns:
        Forecast data for 30/60/90 days
    """
    valid_metrics = ["risk_score", "asset_count", "compliance", "approval_volume"]
    if metric not in valid_metrics:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid metric. Must be one of: {', '.join(valid_metrics)}",
        )

    analyzer = get_trend_analyzer()

    if metric == "risk_score":
        trends = analyzer.get_risk_score_trends(days=days)
    elif metric == "asset_count":
        trends = analyzer.get_asset_growth_trends(days=days)
    elif metric == "compliance":
        trends = analyzer.get_compliance_trends(days=days)
    elif metric == "approval_volume":
        trends = analyzer.get_approval_volume_trends(days=days)

    return {
        "metric": metric,
        "forecast_30d": round(trends.forecast_30d, 2),
        "forecast_60d": round(trends.forecast_60d, 2),
        "forecast_90d": round(trends.forecast_90d, 2),
        "confidence": round(trends.confidence, 2),
        "velocity": round(trends.velocity, 4),
    }


# ============================================================================
# Export Endpoint
# ============================================================================


@router.post("/export")
async def export_dashboard_data(
    format: str = Query("json", description="Export format (json, csv)"),
    include_metrics: bool = Query(True, description="Include risk metrics"),
    include_reports: bool = Query(True, description="Include compliance reports"),
    include_trends: bool = Query(True, description="Include trend analysis"),
) -> Dict[str, Any]:
    """
    Export dashboard data in specified format.

    Args:
        format: Export format ("json" or "csv")
        include_metrics: Include risk metrics
        include_reports: Include compliance reports
        include_trends: Include trend analysis

    Returns:
        Exported dashboard data
    """
    if format not in ["json", "csv"]:
        raise HTTPException(
            status_code=400, detail="Invalid format. Must be 'json' or 'csv'"
        )

    export_data = {
        "exported_at": datetime.utcnow().isoformat(),
        "format": format,
    }

    if include_metrics:
        aggregator = get_risk_metrics_aggregator()
        metrics = aggregator.get_portfolio_metrics()
        export_data["metrics"] = metrics.to_dict()

    if include_reports:
        reporter = get_compliance_reporter()
        executive_summary = reporter.generate_executive_summary()
        export_data["executive_summary"] = executive_summary.to_dict()

    if include_trends:
        analyzer = get_trend_analyzer()
        risk_trends = analyzer.get_risk_score_trends(days=30)
        export_data["risk_trends"] = risk_trends.to_dict()

    # Note: CSV conversion would be implemented here
    # For now, returning JSON structure
    return export_data


# ============================================================================
# Utility Endpoints
# ============================================================================


@router.post("/snapshot")
async def record_snapshot() -> Dict[str, str]:
    """
    Record current state snapshot for trend analysis.

    Should be called periodically (e.g., daily via cron) to build historical data.

    Returns:
        Confirmation message
    """
    analyzer = get_trend_analyzer()
    analyzer.record_snapshot()

    return {
        "status": "success",
        "message": "Snapshot recorded successfully",
        "timestamp": datetime.utcnow().isoformat(),
    }
