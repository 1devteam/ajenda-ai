"""
Compliance Reporting System for Omnipath V2.

This module generates comprehensive compliance reports for audit and regulatory purposes.

Author: Dev Team Lead
Date: 2026-02-26
Built with Pride for Obex Blackvault
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Any, Optional
from enum import Enum
import uuid

from ..registry.asset_registry import get_registry, AssetType, AssetStatus
from ..registry.lineage_tracker import get_tracker
from .risk_scoring import get_risk_scoring_engine, RiskTier
from .regulatory_mapping import RiskLevel
from .risk_metrics import get_risk_metrics_aggregator


class ReportType(str, Enum):
    """Types of compliance reports."""
    EXECUTIVE_SUMMARY = "executive_summary"
    DETAILED_AUDIT = "detailed_audit"
    REGULATORY = "regulatory"
    RISK_ASSESSMENT = "risk_assessment"


@dataclass
class ComplianceReport:
    """
    Comprehensive compliance report.
    
    Provides audit trails, compliance status, and recommendations.
    """
    report_id: str
    report_type: ReportType
    generated_at: datetime
    generated_by: str
    time_period: Tuple[datetime, datetime]
    summary: Dict[str, Any]
    findings: List[Dict[str, Any]]
    recommendations: List[str]
    data: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary."""
        return {
            "report_id": self.report_id,
            "report_type": self.report_type.value,
            "generated_at": self.generated_at.isoformat(),
            "generated_by": self.generated_by,
            "time_period": {
                "start": self.time_period[0].isoformat(),
                "end": self.time_period[1].isoformat(),
            },
            "summary": self.summary,
            "findings": self.findings,
            "recommendations": self.recommendations,
            "data": self.data,
        }


class ComplianceReporter:
    """
    Generates compliance reports for audit and regulatory purposes.
    
    Provides executive summaries, detailed audits, regulatory compliance reports,
    and risk assessment reports.
    """
    
    def __init__(self):
        """Initialize the reporter."""
        self.registry = get_registry()
        self.tracker = get_tracker()
        self.risk_engine = get_risk_scoring_engine()
        self.metrics_aggregator = get_risk_metrics_aggregator()
    
    def generate_executive_summary(
        self,
        generated_by: str = "system",
        days: int = 30
    ) -> ComplianceReport:
        """
        Generate executive summary report.
        
        High-level overview of compliance posture, risk distribution, and key gaps.
        
        Args:
            generated_by: User ID generating the report
            days: Number of days to include in report
            
        Returns:
            ComplianceReport with executive summary
        """
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=days)
        
        # Get metrics
        metrics = self.metrics_aggregator.get_portfolio_metrics()
        compliance_posture = self.metrics_aggregator.get_compliance_posture()
        approval_stats = self.metrics_aggregator.get_approval_queue_stats()
        
        # Summary
        summary = {
            "total_assets": metrics.total_assets,
            "average_risk_score": round(metrics.average_risk_score, 2),
            "compliance_coverage": round(metrics.compliance_coverage, 2),
            "high_risk_assets": metrics.assets_by_tier.get(RiskTier.HIGH.value, 0) + 
                               metrics.assets_by_tier.get(RiskTier.CRITICAL.value, 0),
            "assets_requiring_approval": metrics.assets_requiring_approval,
        }
        
        # Findings
        findings = []
        
        # Finding 1: Risk distribution
        findings.append({
            "category": "Risk Distribution",
            "severity": "info",
            "description": f"Portfolio contains {metrics.total_assets} assets with average risk score {summary['average_risk_score']}",
            "details": {
                "by_tier": metrics.assets_by_tier,
                "by_type": metrics.assets_by_type,
            }
        })
        
        # Finding 2: Compliance coverage
        if compliance_posture["coverage_percentage"] < 100:
            findings.append({
                "category": "Compliance Coverage",
                "severity": "warning",
                "description": f"Only {compliance_posture['coverage_percentage']}% of assets have risk assessments",
                "details": {
                    "assets_without_assessment": metrics.total_assets - compliance_posture["assets_with_risk_assessment"],
                    "compliance_gaps": compliance_posture["compliance_gaps"],
                }
            })
        
        # Finding 3: High-risk assets
        if summary["high_risk_assets"] > 0:
            findings.append({
                "category": "High-Risk Assets",
                "severity": "critical" if summary["high_risk_assets"] > 10 else "warning",
                "description": f"{summary['high_risk_assets']} assets classified as HIGH or CRITICAL risk",
                "details": {
                    "top_risks": [
                        {"asset_id": aid, "score": score, "tier": tier}
                        for aid, score, tier in metrics.top_risks[:5]
                    ]
                }
            })
        
        # Recommendations
        recommendations = []
        
        if compliance_posture["coverage_percentage"] < 100:
            recommendations.append(
                f"Complete risk assessments for {compliance_posture['compliance_gaps']} assets to achieve 100% coverage"
            )
        
        if summary["high_risk_assets"] > 0:
            recommendations.append(
                f"Review and mitigate {summary['high_risk_assets']} high-risk assets through approval workflows"
            )
        
        if metrics.assets_requiring_approval > 0:
            recommendations.append(
                f"Establish approval processes for {metrics.assets_requiring_approval} assets requiring oversight"
            )
        
        return ComplianceReport(
            report_id=str(uuid.uuid4()),
            report_type=ReportType.EXECUTIVE_SUMMARY,
            generated_at=datetime.utcnow(),
            generated_by=generated_by,
            time_period=(start_time, end_time),
            summary=summary,
            findings=findings,
            recommendations=recommendations,
            data={
                "metrics": metrics.to_dict(),
                "compliance_posture": compliance_posture,
                "approval_stats": approval_stats,
            }
        )
    
    def generate_detailed_audit(
        self,
        generated_by: str = "system",
        days: int = 90
    ) -> ComplianceReport:
        """
        Generate detailed audit report.
        
        Complete asset inventory with compliance status, approval history,
        lineage tracking, and tag application history.
        
        Args:
            generated_by: User ID generating the report
            days: Number of days to include in report
            
        Returns:
            ComplianceReport with detailed audit information
        """
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=days)
        
        assets = self.registry.list_all()
        
        # Asset inventory with compliance details
        asset_details = []
        for asset in assets:
            # Get risk score
            risk_score = self.risk_engine.get_score(asset.asset_id)
            
            # Get lineage events
            events = self.tracker.get_events_for_asset(asset.asset_id)
            recent_events = [
                {
                    "event_id": e.event_id,
                    "event_type": e.event_type.value,
                    "timestamp": e.timestamp.isoformat(),
                }
                for e in events
                if e.timestamp >= start_time
            ]
            
            asset_details.append({
                "asset_id": asset.asset_id,
                "name": asset.name,
                "type": asset.asset_type.value,
                "status": asset.status.value,
                "owner": asset.owner,
                "risk_score": risk_score.score if risk_score else None,
                "risk_tier": risk_score.tier.value if risk_score else "unknown",
                "tags": asset.tags,
                "dependencies": asset.dependencies,
                "recent_events": recent_events,
                "created_at": asset.created_at.isoformat() if hasattr(asset, 'created_at') else None,
                "updated_at": asset.updated_at.isoformat() if hasattr(asset, 'updated_at') else None,
            })
        
        # Summary
        summary = {
            "total_assets_audited": len(assets),
            "audit_period_days": days,
            "assets_by_status": {
                status.value: sum(1 for a in assets if a.status == status)
                for status in AssetStatus
            },
            "total_events_in_period": sum(len(a["recent_events"]) for a in asset_details),
        }
        
        # Findings
        findings = []
        
        # Check for deprecated assets still in use
        deprecated_active = [a for a in assets if a.status == AssetStatus.DEPRECATED]
        if deprecated_active:
            findings.append({
                "category": "Deprecated Assets",
                "severity": "warning",
                "description": f"{len(deprecated_active)} deprecated assets still registered",
                "details": {
                    "assets": [a.asset_id for a in deprecated_active]
                }
            })
        
        # Check for assets without tags
        untagged = [a for a in assets if not a.tags]
        if untagged:
            findings.append({
                "category": "Untagged Assets",
                "severity": "info",
                "description": f"{len(untagged)} assets without contextual tags",
                "details": {
                    "assets": [a.asset_id for a in untagged]
                }
            })
        
        # Recommendations
        recommendations = []
        if deprecated_active:
            recommendations.append("Archive or remove deprecated assets to maintain clean inventory")
        if untagged:
            recommendations.append("Apply contextual tags to all assets for better governance")
        
        return ComplianceReport(
            report_id=str(uuid.uuid4()),
            report_type=ReportType.DETAILED_AUDIT,
            generated_at=datetime.utcnow(),
            generated_by=generated_by,
            time_period=(start_time, end_time),
            summary=summary,
            findings=findings,
            recommendations=recommendations,
            data={
                "assets": asset_details,
            }
        )
    
    def generate_regulatory_compliance_report(
        self,
        regulation: str,
        generated_by: str = "system"
    ) -> ComplianceReport:
        """
        Generate regulatory compliance report.
        
        Compliance status for specific regulation (EU AI Act, GDPR, HIPAA, SOX).
        
        Args:
            regulation: Regulation name ("eu_ai_act", "gdpr", "hipaa", "sox")
            generated_by: User ID generating the report
            
        Returns:
            ComplianceReport with regulatory compliance information
        """
        assets = self.registry.list_all()
        
        # Filter assets by regulation
        if regulation == "eu_ai_act":
            relevant_assets = assets  # All assets subject to EU AI Act
            tag_filter = ["eu-ai-act"]
        elif regulation == "gdpr":
            tag_filter = ["pii", "gdpr"]
            relevant_assets = [a for a in assets if any(t in a.tags for t in tag_filter)]
        elif regulation == "hipaa":
            tag_filter = ["phi", "hipaa", "healthcare"]
            relevant_assets = [a for a in assets if any(t in a.tags for t in tag_filter)]
        elif regulation == "sox":
            tag_filter = ["financial", "sox"]
            relevant_assets = [a for a in assets if any(t in a.tags for t in tag_filter)]
        else:
            raise ValueError(f"Unknown regulation: {regulation}")
        
        # Analyze compliance
        compliant = 0
        non_compliant = 0
        partial_compliant = 0
        
        compliance_details = []
        for asset in relevant_assets:
            risk_score = self.risk_engine.get_score(asset.asset_id)
            
            # Check compliance criteria
            has_risk_assessment = risk_score is not None
            has_tags = bool(asset.tags)
            has_documentation = bool(asset.description)
            
            if has_risk_assessment and has_tags and has_documentation:
                status = "compliant"
                compliant += 1
            elif has_risk_assessment or has_tags:
                status = "partial"
                partial_compliant += 1
            else:
                status = "non_compliant"
                non_compliant += 1
            
            compliance_details.append({
                "asset_id": asset.asset_id,
                "name": asset.name,
                "status": status,
                "has_risk_assessment": has_risk_assessment,
                "has_tags": has_tags,
                "has_documentation": has_documentation,
                "risk_tier": risk_score.tier.value if risk_score else "unknown",
            })
        
        # Summary
        total = len(relevant_assets)
        compliance_rate = (compliant / total * 100) if total > 0 else 0.0
        
        summary = {
            "regulation": regulation,
            "total_assets": total,
            "compliant": compliant,
            "partial_compliant": partial_compliant,
            "non_compliant": non_compliant,
            "compliance_rate": round(compliance_rate, 2),
        }
        
        # Findings
        findings = []
        
        if non_compliant > 0:
            findings.append({
                "category": "Non-Compliance",
                "severity": "critical",
                "description": f"{non_compliant} assets do not meet {regulation.upper()} requirements",
                "details": {
                    "assets": [a["asset_id"] for a in compliance_details if a["status"] == "non_compliant"]
                }
            })
        
        if partial_compliant > 0:
            findings.append({
                "category": "Partial Compliance",
                "severity": "warning",
                "description": f"{partial_compliant} assets partially comply with {regulation.upper()}",
                "details": {
                    "assets": [a["asset_id"] for a in compliance_details if a["status"] == "partial"]
                }
            })
        
        # Recommendations
        recommendations = []
        if non_compliant > 0:
            recommendations.append(f"Complete risk assessments and tagging for {non_compliant} non-compliant assets")
        if partial_compliant > 0:
            recommendations.append(f"Address gaps in {partial_compliant} partially compliant assets")
        if compliance_rate < 100:
            recommendations.append(f"Target 100% compliance (currently {compliance_rate}%)")
        
        return ComplianceReport(
            report_id=str(uuid.uuid4()),
            report_type=ReportType.REGULATORY,
            generated_at=datetime.utcnow(),
            generated_by=generated_by,
            time_period=(datetime.utcnow() - timedelta(days=1), datetime.utcnow()),
            summary=summary,
            findings=findings,
            recommendations=recommendations,
            data={
                "compliance_details": compliance_details,
            }
        )
    
    def generate_risk_assessment_report(
        self,
        generated_by: str = "system"
    ) -> ComplianceReport:
        """
        Generate risk assessment report.
        
        Portfolio risk analysis with factor breakdown, high-risk deep dive,
        and mitigation recommendations.
        
        Args:
            generated_by: User ID generating the report
            
        Returns:
            ComplianceReport with risk assessment information
        """
        metrics = self.metrics_aggregator.get_portfolio_metrics()
        heatmap = self.metrics_aggregator.get_risk_heatmap()
        
        # Get top risks with detailed breakdown
        top_risks_detailed = []
        for asset_id, score, tier in metrics.top_risks[:10]:
            asset = self.registry.get(asset_id)
            breakdown = self.risk_engine.get_risk_breakdown(asset_id)
            
            if asset and breakdown:
                top_risks_detailed.append({
                    "asset_id": asset_id,
                    "name": asset.name,
                    "type": asset.asset_type.value,
                    "score": round(score, 2),
                    "tier": tier,
                    "breakdown": {
                        "inherent": round(breakdown.get("inherent", 0), 2),
                        "data_sensitivity": round(breakdown.get("data_sensitivity", 0), 2),
                        "operational": round(breakdown.get("operational_context", 0), 2),
                        "historical": round(breakdown.get("historical", 0), 2),
                    }
                })
        
        # Summary
        summary = {
            "total_assets": metrics.total_assets,
            "average_risk_score": round(metrics.average_risk_score, 2),
            "median_risk_score": round(metrics.median_risk_score, 2),
            "risk_distribution": metrics.assets_by_tier,
            "critical_assets": metrics.assets_by_tier.get(RiskTier.CRITICAL.value, 0),
            "high_assets": metrics.assets_by_tier.get(RiskTier.HIGH.value, 0),
        }
        
        # Findings
        findings = []
        
        # Critical risk assets
        if summary["critical_assets"] > 0:
            findings.append({
                "category": "Critical Risk",
                "severity": "critical",
                "description": f"{summary['critical_assets']} assets at CRITICAL risk level",
                "details": {
                    "requires_immediate_action": True,
                    "assets": [a["asset_id"] for a in top_risks_detailed if a["tier"] == RiskTier.CRITICAL.value]
                }
            })
        
        # High risk concentration
        if summary["average_risk_score"] > 60:
            findings.append({
                "category": "High Average Risk",
                "severity": "warning",
                "description": f"Portfolio average risk score ({summary['average_risk_score']}) exceeds threshold",
                "details": {
                    "threshold": 60,
                    "excess": round(summary["average_risk_score"] - 60, 2),
                }
            })
        
        # Recommendations
        recommendations = []
        if summary["critical_assets"] > 0:
            recommendations.append("Immediately review and mitigate CRITICAL risk assets")
        if summary["high_assets"] + summary["critical_assets"] > metrics.total_assets * 0.2:
            recommendations.append("Portfolio has >20% high/critical risk assets - implement risk reduction program")
        recommendations.append("Regularly review and update risk assessments to maintain accuracy")
        
        return ComplianceReport(
            report_id=str(uuid.uuid4()),
            report_type=ReportType.RISK_ASSESSMENT,
            generated_at=datetime.utcnow(),
            generated_by=generated_by,
            time_period=(datetime.utcnow() - timedelta(days=1), datetime.utcnow()),
            summary=summary,
            findings=findings,
            recommendations=recommendations,
            data={
                "metrics": metrics.to_dict(),
                "heatmap": heatmap.to_dict(),
                "top_risks": top_risks_detailed,
            }
        )


# Global instance
_reporter = None


def get_compliance_reporter() -> ComplianceReporter:
    """Get the global compliance reporter instance."""
    global _reporter
    if _reporter is None:
        _reporter = ComplianceReporter()
    return _reporter
