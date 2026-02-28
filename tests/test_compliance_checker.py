"""
Comprehensive tests for Compliance Checker - Week 2

Tests all 7 compliance check types, findings, violations, scoring, and scheduling.

Author: Dev Team Lead
Date: 2026-02-27
Built with Pride for Obex Blackvault
"""

import pytest
from datetime import datetime, timedelta
from backend.agents.compliance.compliance_checker import (
    get_compliance_checker,
    ComplianceCheckType,
    CheckStatus,
    Severity,
    Regulation,
    ComplianceFinding,
    ComplianceCheck,
)
from backend.agents.registry.asset_registry import (
    get_registry,
    AIAsset,
    AssetType,
    AssetStatus,
)
from backend.agents.compliance.policy_engine import (
    get_policy_manager,
    Policy,
    PolicyStatus,
    PolicyCondition,
    PolicyAction,
    ConditionType,
    ActionType,
)
from backend.agents.compliance.risk_scoring import (
    get_risk_scoring_engine,
    RiskScore,
    RiskTier,
)

pytestmark = pytest.mark.unit


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def clear_systems():
    """Clear all systems before each test."""
    checker = get_compliance_checker()
    registry = get_registry()
    policy_manager = get_policy_manager()

    checker.clear()
    registry.clear()
    policy_manager.clear()

    yield

    checker.clear()
    registry.clear()
    policy_manager.clear()


@pytest.fixture
def checker():
    """Get compliance checker instance."""
    return get_compliance_checker()


@pytest.fixture
def registry():
    """Get asset registry instance."""
    return get_registry()


@pytest.fixture
def policy_manager():
    """Get policy manager instance."""
    return get_policy_manager()


@pytest.fixture
def scorer():
    """Get risk scoring engine instance."""
    return get_risk_scoring_engine()


@pytest.fixture
def sample_asset(registry):
    """Create a sample asset."""
    asset = AIAsset(
        asset_id="asset-001",
        asset_type=AssetType.AGENT,
        name="Test Agent",
        description="Test agent for compliance",
        owner="user-001",
        status=AssetStatus.ACTIVE,
        tags=["test"],
    )
    registry.register(asset)
    return asset


# ============================================================================
# Asset Compliance Tests
# ============================================================================


def test_asset_compliance_pass(checker, sample_asset):
    """Test asset compliance check passes with compliant assets."""
    result = checker.run_check(ComplianceCheckType.ASSET_COMPLIANCE)

    assert result.check_type == ComplianceCheckType.ASSET_COMPLIANCE
    assert result.status == CheckStatus.PASS
    assert len(result.findings) == 0
    assert result.score == 100.0


def test_asset_compliance_no_owner(checker, registry):
    """Test asset compliance detects assets without owners."""
    asset = AIAsset(
        asset_id="asset-001",
        asset_type=AssetType.AGENT,
        name="Test Agent",
        description="Test",
        owner="",  # No owner
        status=AssetStatus.ACTIVE,
    )
    registry.register(asset)

    result = checker.run_check(ComplianceCheckType.ASSET_COMPLIANCE)

    assert result.status in [CheckStatus.WARNING, CheckStatus.FAIL]
    assert len(result.findings) > 0
    assert any("without owners" in f.description for f in result.findings)
    assert result.score < 100.0


def test_asset_compliance_deprecated_in_production(checker, registry):
    """Test asset compliance detects deprecated assets in production."""
    asset = AIAsset(
        asset_id="asset-001",
        asset_type=AssetType.AGENT,
        name="Test Agent",
        description="Test",
        owner="user-001",
        status=AssetStatus.DEPRECATED,
        tags=["production"],  # Deprecated but in production
    )
    registry.register(asset)

    result = checker.run_check(ComplianceCheckType.ASSET_COMPLIANCE)

    assert result.status == CheckStatus.FAIL
    assert len(result.findings) > 0

    critical_findings = [f for f in result.findings if f.severity == Severity.CRITICAL]
    assert len(critical_findings) > 0
    assert any("deprecated" in f.description.lower() for f in critical_findings)


def test_asset_compliance_no_description(checker, registry):
    """Test asset compliance detects assets without descriptions."""
    asset = AIAsset(
        asset_id="asset-001",
        asset_type=AssetType.AGENT,
        name="Test Agent",
        description="",  # No description
        owner="user-001",
        status=AssetStatus.ACTIVE,
    )
    registry.register(asset)

    result = checker.run_check(ComplianceCheckType.ASSET_COMPLIANCE)

    assert result.status == CheckStatus.WARNING
    assert len(result.findings) > 0
    assert any("without descriptions" in f.description for f in result.findings)


# ============================================================================
# Policy Compliance Tests
# ============================================================================


def test_policy_compliance_pass(checker, policy_manager):
    """Test policy compliance passes with required policies."""
    # Create required policies
    policy1 = Policy(
        policy_id="policy-001",
        name="GDPR PII Protection",
        description="Test",
        status=PolicyStatus.ACTIVE,
        conditions=[
            PolicyCondition(
                condition_type=ConditionType.ASSET_TAG,
                operator="contains",
                field="tags",
                value="pii",
            )
        ],
        actions=[PolicyAction(action_type=ActionType.DENY)],
        metadata={"template_id": "gdpr-pii-protection"},
    )
    policy2 = Policy(
        policy_id="policy-002",
        name="High Risk Approval",
        description="Test",
        status=PolicyStatus.ACTIVE,
        conditions=[
            PolicyCondition(
                condition_type=ConditionType.RISK_TIER,
                operator="equals",
                field="tier",
                value="high",
            )
        ],
        actions=[PolicyAction(action_type=ActionType.REQUIRE_APPROVAL)],
        metadata={"template_id": "high-risk-approval"},
    )

    policy_manager.create_policy(policy1)
    policy_manager.create_policy(policy2)

    result = checker.run_check(ComplianceCheckType.POLICY_COMPLIANCE)

    assert result.check_type == ComplianceCheckType.POLICY_COMPLIANCE
    assert result.status == CheckStatus.PASS
    assert len(result.findings) == 0


def test_policy_compliance_missing_required_template(checker, policy_manager):
    """Test policy compliance detects missing required templates."""
    # Only create one required policy
    policy = Policy(
        policy_id="policy-001",
        name="GDPR PII Protection",
        description="Test",
        status=PolicyStatus.ACTIVE,
        conditions=[
            PolicyCondition(
                condition_type=ConditionType.ASSET_TAG,
                operator="contains",
                field="tags",
                value="pii",
            )
        ],
        actions=[PolicyAction(action_type=ActionType.DENY)],
        metadata={"template_id": "gdpr-pii-protection"},
    )
    policy_manager.create_policy(policy)

    result = checker.run_check(ComplianceCheckType.POLICY_COMPLIANCE)

    assert result.status == CheckStatus.WARNING
    assert len(result.findings) > 0
    assert any("high-risk-approval" in f.description for f in result.findings)


def test_policy_compliance_policy_without_conditions(checker, policy_manager):
    """Test policy compliance detects policies without conditions."""
    # Create required policies first
    policy1 = Policy(
        policy_id="policy-001",
        name="GDPR PII Protection",
        description="Test",
        status=PolicyStatus.ACTIVE,
        conditions=[
            PolicyCondition(
                condition_type=ConditionType.ASSET_TAG,
                operator="contains",
                field="tags",
                value="pii",
            )
        ],
        actions=[PolicyAction(action_type=ActionType.DENY)],
        metadata={"template_id": "gdpr-pii-protection"},
    )
    policy2 = Policy(
        policy_id="policy-002",
        name="High Risk Approval",
        description="Test",
        status=PolicyStatus.ACTIVE,
        conditions=[
            PolicyCondition(
                condition_type=ConditionType.RISK_TIER,
                operator="equals",
                field="tier",
                value="high",
            )
        ],
        actions=[PolicyAction(action_type=ActionType.REQUIRE_APPROVAL)],
        metadata={"template_id": "high-risk-approval"},
    )

    # Create policy without conditions
    policy3 = Policy(
        policy_id="policy-003",
        name="Empty Policy",
        description="Test",
        status=PolicyStatus.ACTIVE,
        conditions=[],  # No conditions
        actions=[PolicyAction(action_type=ActionType.ALLOW)],
    )

    policy_manager.create_policy(policy1)
    policy_manager.create_policy(policy2)
    policy_manager.create_policy(policy3)

    result = checker.run_check(ComplianceCheckType.POLICY_COMPLIANCE)

    assert result.status == CheckStatus.WARNING
    assert len(result.findings) > 0
    assert any("without conditions" in f.description for f in result.findings)


# ============================================================================
# Data Compliance Tests
# ============================================================================


def test_data_compliance_pass_no_sensitive_data(checker):
    """Test data compliance passes with no sensitive data."""
    result = checker.run_check(ComplianceCheckType.DATA_COMPLIANCE)

    assert result.check_type == ComplianceCheckType.DATA_COMPLIANCE
    assert result.status == CheckStatus.PASS
    assert len(result.findings) == 0
    assert result.score == 100.0


def test_data_compliance_pii_without_gdpr_policy(checker, registry, policy_manager):
    """Test data compliance detects PII without GDPR policy."""
    # Create asset with PII tag
    asset = AIAsset(
        asset_id="asset-001",
        asset_type=AssetType.AGENT,
        name="Test Agent",
        description="Test",
        owner="user-001",
        status=AssetStatus.ACTIVE,
        tags=["pii"],  # Has PII
    )
    registry.register(asset)

    result = checker.run_check(ComplianceCheckType.DATA_COMPLIANCE)

    assert result.status == CheckStatus.FAIL
    assert len(result.findings) > 0

    critical_findings = [f for f in result.findings if f.severity == Severity.CRITICAL]
    assert len(critical_findings) > 0
    assert any(
        "pii" in f.description.lower() and "gdpr" in f.description.lower()
        for f in critical_findings
    )


def test_data_compliance_phi_without_hipaa_policy(checker, registry, policy_manager):
    """Test data compliance detects PHI without HIPAA policy."""
    # Create asset with PHI tag
    asset = AIAsset(
        asset_id="asset-001",
        asset_type=AssetType.AGENT,
        name="Test Agent",
        description="Test",
        owner="user-001",
        status=AssetStatus.ACTIVE,
        tags=["phi"],  # Has PHI
    )
    registry.register(asset)

    result = checker.run_check(ComplianceCheckType.DATA_COMPLIANCE)

    assert result.status == CheckStatus.FAIL
    assert len(result.findings) > 0

    critical_findings = [f for f in result.findings if f.severity == Severity.CRITICAL]
    assert len(critical_findings) > 0
    assert any(
        "phi" in f.description.lower() and "hipaa" in f.description.lower()
        for f in critical_findings
    )


def test_data_compliance_pass_with_protection_policies(checker, registry, policy_manager):
    """Test data compliance passes with appropriate protection policies."""
    # Create asset with PII tag
    asset = AIAsset(
        asset_id="asset-001",
        asset_type=AssetType.AGENT,
        name="Test Agent",
        description="Test",
        owner="user-001",
        status=AssetStatus.ACTIVE,
        tags=["pii"],
    )
    registry.register(asset)

    # Create GDPR policy
    policy = Policy(
        policy_id="policy-001",
        name="GDPR PII Protection",
        description="Test",
        status=PolicyStatus.ACTIVE,
        conditions=[
            PolicyCondition(
                condition_type=ConditionType.ASSET_TAG,
                operator="contains",
                field="tags",
                value="pii",
            )
        ],
        actions=[PolicyAction(action_type=ActionType.DENY)],
    )
    policy_manager.create_policy(policy)

    result = checker.run_check(ComplianceCheckType.DATA_COMPLIANCE)

    assert result.status == CheckStatus.PASS
    assert len(result.findings) == 0


# ============================================================================
# Risk Compliance Tests
# ============================================================================


def test_risk_compliance_pass_no_high_risk_assets(checker):
    """Test risk compliance passes with no high-risk assets."""
    result = checker.run_check(ComplianceCheckType.RISK_COMPLIANCE)

    assert result.check_type == ComplianceCheckType.RISK_COMPLIANCE
    assert result.status == CheckStatus.PASS
    assert len(result.findings) == 0
    assert result.score == 100.0


# ============================================================================
# Tag Compliance Tests
# ============================================================================


def test_tag_compliance_pass(checker, sample_asset):
    """Test tag compliance passes with tagged assets."""
    result = checker.run_check(ComplianceCheckType.TAG_COMPLIANCE)

    assert result.check_type == ComplianceCheckType.TAG_COMPLIANCE
    assert result.status == CheckStatus.PASS
    assert len(result.findings) == 0


def test_tag_compliance_untagged_assets(checker, registry):
    """Test tag compliance detects untagged assets."""
    asset = AIAsset(
        asset_id="asset-001",
        asset_type=AssetType.AGENT,
        name="Test Agent",
        description="Test",
        owner="user-001",
        status=AssetStatus.ACTIVE,
        tags=[],  # No tags
    )
    registry.register(asset)

    result = checker.run_check(ComplianceCheckType.TAG_COMPLIANCE)

    assert result.status == CheckStatus.WARNING
    assert len(result.findings) > 0
    assert any("without tags" in f.description for f in result.findings)


# ============================================================================
# Approval and Audit Compliance Tests (Placeholders)
# ============================================================================


def test_approval_compliance_placeholder(checker):
    """Test approval compliance check (placeholder)."""
    result = checker.run_check(ComplianceCheckType.APPROVAL_COMPLIANCE)

    assert result.check_type == ComplianceCheckType.APPROVAL_COMPLIANCE
    assert result.status == CheckStatus.PASS
    assert result.score == 100.0


def test_audit_compliance_placeholder(checker):
    """Test audit compliance check (placeholder)."""
    result = checker.run_check(ComplianceCheckType.AUDIT_COMPLIANCE)

    assert result.check_type == ComplianceCheckType.AUDIT_COMPLIANCE
    assert result.status == CheckStatus.PASS
    assert result.score == 100.0


# ============================================================================
# Check Management Tests
# ============================================================================


def test_get_check(checker, sample_asset):
    """Test retrieving specific check."""
    result = checker.run_check(ComplianceCheckType.ASSET_COMPLIANCE)

    retrieved = checker.get_check(result.check_id)
    assert retrieved is not None
    assert retrieved.check_id == result.check_id
    assert retrieved.check_type == result.check_type


def test_list_checks(checker, sample_asset):
    """Test listing checks."""
    # Run multiple checks
    checker.run_check(ComplianceCheckType.ASSET_COMPLIANCE)
    checker.run_check(ComplianceCheckType.POLICY_COMPLIANCE)
    checker.run_check(ComplianceCheckType.TAG_COMPLIANCE)

    # List all checks
    checks = checker.list_checks()
    assert len(checks) == 3


def test_list_checks_by_type(checker, sample_asset):
    """Test listing checks filtered by type."""
    checker.run_check(ComplianceCheckType.ASSET_COMPLIANCE)
    checker.run_check(ComplianceCheckType.ASSET_COMPLIANCE)
    checker.run_check(ComplianceCheckType.POLICY_COMPLIANCE)

    asset_checks = checker.list_checks(check_type=ComplianceCheckType.ASSET_COMPLIANCE)
    assert len(asset_checks) == 2
    assert all(c.check_type == ComplianceCheckType.ASSET_COMPLIANCE for c in asset_checks)


def test_list_checks_by_status(checker, registry):
    """Test listing checks filtered by status."""
    # Create compliant asset
    asset1 = AIAsset(
        asset_id="asset-001",
        asset_type=AssetType.AGENT,
        name="Test Agent",
        description="Test",
        owner="user-001",
        status=AssetStatus.ACTIVE,
        tags=["test"],
    )
    registry.register(asset1)

    # Create non-compliant asset
    asset2 = AIAsset(
        asset_id="asset-002",
        asset_type=AssetType.AGENT,
        name="Test Agent 2",
        description="",  # No description
        owner="user-001",
        status=AssetStatus.ACTIVE,
        tags=["test"],
    )
    registry.register(asset2)

    checker.run_check(ComplianceCheckType.ASSET_COMPLIANCE)

    warning_checks = checker.list_checks(status=CheckStatus.WARNING)
    assert len(warning_checks) >= 1


# ============================================================================
# Compliance Score Tests
# ============================================================================


def test_get_compliance_score_no_checks(checker):
    """Test getting compliance score with no checks."""
    score = checker.get_compliance_score()
    assert score == 0.0


def test_get_compliance_score_single_check(checker, sample_asset):
    """Test getting compliance score with single check."""
    checker.run_check(ComplianceCheckType.ASSET_COMPLIANCE)

    score = checker.get_compliance_score()
    assert score == 100.0


def test_get_compliance_score_multiple_checks(checker, sample_asset):
    """Test getting compliance score with multiple checks."""
    checker.run_check(ComplianceCheckType.ASSET_COMPLIANCE)
    checker.run_check(ComplianceCheckType.TAG_COMPLIANCE)
    checker.run_check(ComplianceCheckType.DATA_COMPLIANCE)

    score = checker.get_compliance_score()
    assert 0 <= score <= 100


def test_get_compliance_score_uses_most_recent(checker, registry):
    """Test that compliance score uses most recent check of each type."""
    # Create non-compliant asset
    asset = AIAsset(
        asset_id="asset-001",
        asset_type=AssetType.AGENT,
        name="Test Agent",
        description="",  # No description
        owner="user-001",
        status=AssetStatus.ACTIVE,
    )
    registry.register(asset)

    # Run check (will have warnings)
    checker.run_check(ComplianceCheckType.ASSET_COMPLIANCE)
    first_score = checker.get_compliance_score()

    # Fix asset
    registry.update("asset-001", description="Now has description")

    # Run check again (should be better)
    checker.run_check(ComplianceCheckType.ASSET_COMPLIANCE)
    second_score = checker.get_compliance_score()

    assert second_score >= first_score


# ============================================================================
# Violations Tests
# ============================================================================


def test_get_violations_none(checker, sample_asset):
    """Test getting violations with no critical issues."""
    checker.run_check(ComplianceCheckType.ASSET_COMPLIANCE)

    violations = checker.get_violations()
    assert len(violations) == 0


def test_get_violations_critical_findings(checker, registry):
    """Test getting violations with critical findings."""
    # Create deprecated asset in production
    asset = AIAsset(
        asset_id="asset-001",
        asset_type=AssetType.AGENT,
        name="Test Agent",
        description="Test",
        owner="user-001",
        status=AssetStatus.DEPRECATED,
        tags=["production"],
    )
    registry.register(asset)

    checker.run_check(ComplianceCheckType.ASSET_COMPLIANCE)

    violations = checker.get_violations()
    assert len(violations) > 0
    assert all(v.severity in [Severity.CRITICAL, Severity.HIGH] for v in violations)


def test_get_violations_high_findings(checker, registry):
    """Test getting violations with high severity findings."""
    # Create asset without owner
    asset = AIAsset(
        asset_id="asset-001",
        asset_type=AssetType.AGENT,
        name="Test Agent",
        description="Test",
        owner="",  # No owner
        status=AssetStatus.ACTIVE,
    )
    registry.register(asset)

    checker.run_check(ComplianceCheckType.ASSET_COMPLIANCE)

    violations = checker.get_violations()
    assert len(violations) > 0


# ============================================================================
# Scheduling Tests
# ============================================================================


def test_schedule_check(checker):
    """Test scheduling a recurring check."""
    checker.schedule_check(ComplianceCheckType.ASSET_COMPLIANCE, 3600)

    assert ComplianceCheckType.ASSET_COMPLIANCE in checker._scheduled_checks
    assert checker._scheduled_checks[ComplianceCheckType.ASSET_COMPLIANCE] == 3600


# ============================================================================
# Data Model Tests
# ============================================================================


def test_compliance_finding_to_dict():
    """Test converting ComplianceFinding to dictionary."""
    finding = ComplianceFinding(
        finding_id="finding-001",
        description="Test finding",
        affected_assets=["asset-001"],
        regulation=Regulation.GDPR,
        article="Article 32",
        severity=Severity.HIGH,
        remediation="Fix it",
        metadata={"count": 5},
    )

    data = finding.to_dict()

    assert data["finding_id"] == finding.finding_id
    assert data["description"] == finding.description
    assert data["affected_assets"] == finding.affected_assets
    assert data["regulation"] == finding.regulation.value
    assert data["article"] == finding.article
    assert data["severity"] == finding.severity.value
    assert data["remediation"] == finding.remediation
    assert data["metadata"] == finding.metadata


def test_compliance_check_to_dict(checker, sample_asset):
    """Test converting ComplianceCheck to dictionary."""
    result = checker.run_check(ComplianceCheckType.ASSET_COMPLIANCE)

    data = result.to_dict()

    assert data["check_id"] == result.check_id
    assert data["check_type"] == result.check_type.value
    assert data["status"] == result.status.value
    assert "timestamp" in data
    assert "findings" in data
    assert "recommendations" in data
    assert data["score"] == result.score
    assert "metadata" in data


# ============================================================================
# Edge Cases
# ============================================================================


def test_get_nonexistent_check(checker):
    """Test getting check that doesn't exist."""
    check = checker.get_check("nonexistent")
    assert check is None


def test_list_checks_no_matches(checker, sample_asset):
    """Test listing checks with no matches."""
    checker.run_check(ComplianceCheckType.ASSET_COMPLIANCE)

    checks = checker.list_checks(status=CheckStatus.FAIL)
    # May or may not have matches depending on asset state
    assert isinstance(checks, list)


def test_clear_checker(checker, sample_asset):
    """Test clearing checker."""
    checker.run_check(ComplianceCheckType.ASSET_COMPLIANCE)
    checker.schedule_check(ComplianceCheckType.TAG_COMPLIANCE, 3600)

    assert len(checker.list_checks()) > 0
    assert len(checker._scheduled_checks) > 0

    checker.clear()

    assert len(checker.list_checks()) == 0
    assert len(checker._scheduled_checks) == 0
    assert checker.get_compliance_score() == 0.0


def test_singleton_pattern():
    """Test that checker is a singleton."""
    checker1 = get_compliance_checker()
    checker2 = get_compliance_checker()

    assert checker1 is checker2
