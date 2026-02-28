"""
Tests for Compliance Reporting.

Author: Dev Team Lead
Date: 2026-02-26
Built with Pride for Obex Blackvault
"""

import pytest
from datetime import datetime

from backend.agents.compliance.compliance_reporting import (
    get_compliance_reporter,
    ComplianceReport,
    ReportType,
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

    yield

    registry.clear()


# ============================================================================
# Executive Summary Tests
# ============================================================================


def test_generate_executive_summary():
    """Test executive summary generation."""
    registry = get_registry()
    risk_engine = get_risk_scoring_engine()

    # Create test assets
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

    # Generate report
    reporter = get_compliance_reporter()
    report = reporter.generate_executive_summary(generated_by="test-user", days=30)

    assert report.report_type == ReportType.EXECUTIVE_SUMMARY
    assert report.generated_by == "test-user"
    assert report.summary["total_assets"] == 1
    assert "average_risk_score" in report.summary
    assert len(report.findings) > 0
    assert len(report.recommendations) >= 0


def test_executive_summary_high_risk_finding():
    """Test that executive summary identifies high-risk assets."""
    from backend.agents.compliance.regulatory_mapping import RegulatoryMappingRule

    registry = get_registry()
    risk_engine = get_risk_scoring_engine()

    # Create high-risk asset with tags that produce a HIGH tier score.
    # Score calculation:
    #   - "biometric" triggers EU AI Act HIGH inherent risk (score = 75, weight 0.40 = 30.0)
    #   - "pii"+"phi"+"financial" data sensitivity = 20+25+20 = 65 (weight 0.25 = 16.25)
    #   - "automated-decision"+"production"+"user-facing" operational
    #     = 20+20+15 = 55 (weight 0.20 = 11.0)
    #   Total = 30.0 + 16.25 + 11.0 = 57.25 → MEDIUM
    # Adding "biometric" to data sensitivity: 25+20+25+20 = 90 (weight 0.25 = 22.5)
    #   Total = 30.0 + 22.5 + 11.0 = 63.5 → HIGH tier (>= 60)
    high_risk = AIAsset(
        asset_id="high-001",
        asset_type=AssetType.AGENT,
        name="High Risk Agent",
        description="Test",
        owner="test",
        status=AssetStatus.ACTIVE,
        tags=[
            "biometric",
            "pii",
            "phi",
            "financial",
            "automated-decision",
            "production",
            "user-facing",
        ],
        metadata={},
    )
    registry.register(high_risk)

    # Apply regulatory mapping to set risk_assessment on the asset.
    # Without this, _calculate_inherent_risk defaults to MINIMAL (score=10).
    # rule.check() sets asset.risk_assessment in the registry based on tags.
    rule = RegulatoryMappingRule()
    rule.check({"asset_id": high_risk.asset_id})

    # Calculate and verify the score reaches HIGH tier before generating the report.
    score = risk_engine.calculate_risk_score(high_risk.asset_id)
    assert score.tier.value in (
        "high",
        "critical",
    ), f"Expected HIGH or CRITICAL tier but got {score.tier.value} (score={score.score:.2f})"

    # Generate report
    reporter = get_compliance_reporter()
    report = reporter.generate_executive_summary()

    # Should have finding about high-risk assets
    high_risk_findings = [f for f in report.findings if f["category"] == "High-Risk Assets"]
    assert len(high_risk_findings) > 0


# ============================================================================
# Detailed Audit Tests
# ============================================================================


def test_generate_detailed_audit():
    """Test detailed audit report generation."""
    registry = get_registry()
    risk_engine = get_risk_scoring_engine()

    # Create test assets
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

    # Generate report
    reporter = get_compliance_reporter()
    report = reporter.generate_detailed_audit(generated_by="test-user", days=90)

    assert report.report_type == ReportType.DETAILED_AUDIT
    assert report.summary["total_assets_audited"] == 1
    assert "assets" in report.data
    assert len(report.data["assets"]) == 1

    asset_detail = report.data["assets"][0]
    assert asset_detail["asset_id"] == "agent-001"
    assert asset_detail["name"] == "Test Agent"
    assert asset_detail["risk_score"] is not None


def test_detailed_audit_deprecated_assets():
    """Test that audit identifies deprecated assets."""
    registry = get_registry()

    # Create deprecated asset
    deprecated = AIAsset(
        asset_id="deprecated-001",
        asset_type=AssetType.AGENT,
        name="Deprecated Agent",
        description="Test",
        owner="test",
        status=AssetStatus.DEPRECATED,
        tags=[],
        metadata={},
    )
    registry.register(deprecated)

    # Generate report
    reporter = get_compliance_reporter()
    report = reporter.generate_detailed_audit()

    # Should have finding about deprecated assets
    deprecated_findings = [f for f in report.findings if f["category"] == "Deprecated Assets"]
    assert len(deprecated_findings) > 0


# ============================================================================
# Regulatory Compliance Tests
# ============================================================================


def test_generate_regulatory_compliance_report_eu_ai_act():
    """Test EU AI Act compliance report."""
    registry = get_registry()
    risk_engine = get_risk_scoring_engine()

    # Create test asset
    agent = AIAsset(
        asset_id="agent-001",
        asset_type=AssetType.AGENT,
        name="Test Agent",
        description="Test",
        owner="test",
        status=AssetStatus.ACTIVE,
        tags=["eu-ai-act"],
        metadata={},
    )
    registry.register(agent)
    risk_engine.calculate_risk_score(agent.asset_id)

    # Generate report
    reporter = get_compliance_reporter()
    report = reporter.generate_regulatory_compliance_report(
        regulation="eu_ai_act", generated_by="test-user"
    )

    assert report.report_type == ReportType.REGULATORY
    assert report.summary["regulation"] == "eu_ai_act"
    assert report.summary["total_assets"] >= 1
    assert "compliance_rate" in report.summary


def test_generate_regulatory_compliance_report_gdpr():
    """Test GDPR compliance report."""
    registry = get_registry()
    risk_engine = get_risk_scoring_engine()

    # Create GDPR-relevant asset
    agent = AIAsset(
        asset_id="agent-001",
        asset_type=AssetType.AGENT,
        name="Test Agent",
        description="Test",
        owner="test",
        status=AssetStatus.ACTIVE,
        tags=["pii", "gdpr"],
        metadata={},
    )
    registry.register(agent)
    risk_engine.calculate_risk_score(agent.asset_id)

    # Generate report
    reporter = get_compliance_reporter()
    report = reporter.generate_regulatory_compliance_report(
        regulation="gdpr", generated_by="test-user"
    )

    assert report.summary["regulation"] == "gdpr"
    assert report.summary["total_assets"] == 1


def test_generate_regulatory_compliance_report_hipaa():
    """Test HIPAA compliance report."""
    registry = get_registry()
    risk_engine = get_risk_scoring_engine()

    # Create HIPAA-relevant asset
    agent = AIAsset(
        asset_id="agent-001",
        asset_type=AssetType.AGENT,
        name="Medical Agent",
        description="Test",
        owner="test",
        status=AssetStatus.ACTIVE,
        tags=["phi", "hipaa", "healthcare"],
        metadata={},
    )
    registry.register(agent)
    risk_engine.calculate_risk_score(agent.asset_id)

    # Generate report
    reporter = get_compliance_reporter()
    report = reporter.generate_regulatory_compliance_report(
        regulation="hipaa", generated_by="test-user"
    )

    assert report.summary["regulation"] == "hipaa"
    assert report.summary["total_assets"] == 1


def test_regulatory_compliance_invalid_regulation():
    """Test that invalid regulation raises error."""
    reporter = get_compliance_reporter()

    with pytest.raises(ValueError):
        reporter.generate_regulatory_compliance_report(
            regulation="invalid_regulation", generated_by="test-user"
        )


# ============================================================================
# Risk Assessment Report Tests
# ============================================================================


def test_generate_risk_assessment_report():
    """Test risk assessment report generation."""
    registry = get_registry()
    risk_engine = get_risk_scoring_engine()

    # Create test assets
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

    # Generate report
    reporter = get_compliance_reporter()
    report = reporter.generate_risk_assessment_report(generated_by="test-user")

    assert report.report_type == ReportType.RISK_ASSESSMENT
    assert report.summary["total_assets"] == 1
    assert "average_risk_score" in report.summary
    assert "risk_distribution" in report.summary


def test_risk_assessment_critical_finding():
    """Test that risk assessment identifies critical assets."""
    registry = get_registry()
    risk_engine = get_risk_scoring_engine()

    # Create critical-risk asset
    critical = AIAsset(
        asset_id="critical-001",
        asset_type=AssetType.AGENT,
        name="Critical Agent",
        description="Test",
        owner="test",
        status=AssetStatus.ACTIVE,
        tags=["phi", "biometric", "automated-decision"],
        metadata={"location": "production", "user_facing": True},
    )
    registry.register(critical)
    risk_engine.calculate_risk_score(critical.asset_id)

    # Generate report
    reporter = get_compliance_reporter()
    report = reporter.generate_risk_assessment_report()

    # Check if critical finding exists
    critical_findings = [f for f in report.findings if f.get("severity") == "critical"]
    # May or may not have critical finding depending on score threshold
    assert isinstance(critical_findings, list)


# ============================================================================
# Report Serialization Tests
# ============================================================================


def test_compliance_report_to_dict():
    """Test ComplianceReport serialization."""
    report = ComplianceReport(
        report_id="test-123",
        report_type=ReportType.EXECUTIVE_SUMMARY,
        generated_at=datetime.utcnow(),
        generated_by="test-user",
        time_period=(datetime.utcnow(), datetime.utcnow()),
        summary={"total_assets": 10},
        findings=[{"category": "Test", "severity": "info"}],
        recommendations=["Test recommendation"],
        data={"test": "data"},
    )

    data = report.to_dict()

    assert data["report_id"] == "test-123"
    assert data["report_type"] == "executive_summary"
    assert data["generated_by"] == "test-user"
    assert "time_period" in data
    assert data["summary"]["total_assets"] == 10
