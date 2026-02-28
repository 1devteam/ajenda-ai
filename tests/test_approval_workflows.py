"""
Tests for Approval Workflows.

Author: Dev Team Lead
Date: 2026-02-26
Built with Pride for Obex Blackvault
"""

import pytest
from datetime import datetime, timedelta

from backend.agents.compliance.approval_workflows import (
    get_approval_workflow,
    ApprovalState,
    ApprovalPolicy,
)
from backend.agents.compliance.risk_scoring import get_risk_scoring_engine, RiskTier, RiskScore
from backend.agents.compliance.regulatory_mapping import AuthorityLevel
from backend.agents.registry.asset_registry import get_registry, AIAsset, AssetType, AssetStatus
from backend.agents.registry.lineage_tracker import get_tracker
pytestmark = pytest.mark.unit



@pytest.fixture(autouse=True)
def clear_state():
    """Clear all state before each test."""
    registry = get_registry()
    registry.clear()

    # Must clear both dicts together: clearing only _events leaves stale IDs
    # in _events_by_asset, causing KeyError in get_events_for_asset().
    tracker = get_tracker()
    tracker._events.clear()
    tracker._events_by_asset.clear()

    workflow = get_approval_workflow()
    workflow._requests.clear()

    yield

    # Cleanup
    registry.clear()
    tracker._events.clear()
    tracker._events_by_asset.clear()
    workflow._requests.clear()


@pytest.fixture
def sample_asset_with_score():
    """Create an asset with risk score."""
    asset = AIAsset(
        asset_id="test-001",
        asset_type=AssetType.AGENT,
        name="Test Agent",
        description="Test agent",
        owner="test-owner",
        status=AssetStatus.ACTIVE,
        tags=["production"],
        metadata={},
    )
    
    # Add risk score
    asset.risk_score = RiskScore(
        asset_id="test-001",
        score=65.0,
        tier=RiskTier.HIGH,
        breakdown={},
        calculated_at=datetime.utcnow(),
        calculated_by="test",
    )
    
    return asset


# ============================================================================
# Approval Request Creation Tests
# ============================================================================

def test_create_approval_request(sample_asset_with_score):
    """Test creating an approval request."""
    registry = get_registry()
    registry.register(sample_asset_with_score)
    
    workflow = get_approval_workflow()
    request = workflow.create_approval_request(
        asset_id="test-001",
        operation="execute",
        requester_id="user-001",
        justification="Need to run analysis",
    )
    
    assert request.request_id is not None
    assert request.asset_id == "test-001"
    assert request.operation == "execute"
    assert request.requester_id == "user-001"
    assert request.risk_tier == RiskTier.HIGH
    assert request.state == ApprovalState.PENDING
    assert request.required_approver_level == AuthorityLevel.COMPLIANCE_OFFICER


def test_create_approval_request_asset_not_found():
    """Test creating approval request for non-existent asset."""
    workflow = get_approval_workflow()
    
    with pytest.raises(ValueError, match="not found"):
        workflow.create_approval_request(
            asset_id="nonexistent",
            operation="execute",
            requester_id="user-001",
        )


def test_create_approval_request_auto_calculates_risk():
    """Test creating approval request auto-calculates risk score if missing."""
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
    
    workflow = get_approval_workflow()
    
    # Should auto-calculate risk score
    request = workflow.create_approval_request(
        asset_id="test-001",
        operation="execute",
        requester_id="user-001",
    )
    
    assert request is not None
    assert request.risk_tier is not None


# ============================================================================
# Approval Matrix Tests
# ============================================================================

def test_approval_matrix_minimal():
    """Test approval matrix for minimal risk."""
    asset = AIAsset(
        asset_id="minimal-001",
        asset_type=AssetType.AGENT,
        name="Minimal Agent",
        description="Test",
        owner="test",
        status=AssetStatus.ACTIVE,
        tags=[],
        metadata={},
    )
    asset.risk_score = RiskScore(
        asset_id="minimal-001",
        score=10.0,
        tier=RiskTier.MINIMAL,
        breakdown={},
        calculated_at=datetime.utcnow(),
        calculated_by="test",
    )
    
    registry = get_registry()
    registry.register(asset)
    
    workflow = get_approval_workflow()
    request = workflow.create_approval_request(
        asset_id="minimal-001",
        operation="execute",
        requester_id="user-001",
    )
    
    # Minimal risk should have no required approver (auto-approved)
    assert request.required_approver_level is None


def test_approval_matrix_low():
    """Test approval matrix for low risk."""
    asset = AIAsset(
        asset_id="low-001",
        asset_type=AssetType.AGENT,
        name="Low Risk Agent",
        description="Test",
        owner="test",
        status=AssetStatus.ACTIVE,
        tags=[],
        metadata={},
    )
    asset.risk_score = RiskScore(
        asset_id="low-001",
        score=25.0,
        tier=RiskTier.LOW,
        breakdown={},
        calculated_at=datetime.utcnow(),
        calculated_by="test",
    )
    
    registry = get_registry()
    registry.register(asset)
    
    workflow = get_approval_workflow()
    request = workflow.create_approval_request(
        asset_id="low-001",
        operation="execute",
        requester_id="user-001",
    )
    
    assert request.required_approver_level == AuthorityLevel.OPERATOR


def test_approval_matrix_medium():
    """Test approval matrix for medium risk."""
    asset = AIAsset(
        asset_id="medium-001",
        asset_type=AssetType.AGENT,
        name="Medium Risk Agent",
        description="Test",
        owner="test",
        status=AssetStatus.ACTIVE,
        tags=[],
        metadata={},
    )
    asset.risk_score = RiskScore(
        asset_id="medium-001",
        score=45.0,
        tier=RiskTier.MEDIUM,
        breakdown={},
        calculated_at=datetime.utcnow(),
        calculated_by="test",
    )
    
    registry = get_registry()
    registry.register(asset)
    
    workflow = get_approval_workflow()
    request = workflow.create_approval_request(
        asset_id="medium-001",
        operation="execute",
        requester_id="user-001",
    )
    
    assert request.required_approver_level == AuthorityLevel.ADMIN


def test_approval_matrix_critical():
    """Test approval matrix for critical risk."""
    asset = AIAsset(
        asset_id="critical-001",
        asset_type=AssetType.AGENT,
        name="Critical Risk Agent",
        description="Test",
        owner="test",
        status=AssetStatus.ACTIVE,
        tags=[],
        metadata={},
    )
    asset.risk_score = RiskScore(
        asset_id="critical-001",
        score=85.0,
        tier=RiskTier.CRITICAL,
        breakdown={},
        calculated_at=datetime.utcnow(),
        calculated_by="test",
    )
    
    registry = get_registry()
    registry.register(asset)
    
    workflow = get_approval_workflow()
    request = workflow.create_approval_request(
        asset_id="critical-001",
        operation="execute",
        requester_id="user-001",
    )
    
    assert request.required_approver_level == AuthorityLevel.COMPLIANCE_OFFICER


# ============================================================================
# Approval Actions Tests
# ============================================================================

def test_approve_request(sample_asset_with_score):
    """Test approving an approval request."""
    registry = get_registry()
    registry.register(sample_asset_with_score)
    
    workflow = get_approval_workflow()
    request = workflow.create_approval_request(
        asset_id="test-001",
        operation="execute",
        requester_id="user-001",
    )
    
    success = workflow.approve_request(
        request_id=request.request_id,
        approver_id="compliance-officer-001",
        notes="Approved with oversight",
    )
    
    assert success is True
    
    updated_request = workflow.get_request(request.request_id)
    assert updated_request.state == ApprovalState.APPROVED
    assert updated_request.approver_id == "compliance-officer-001"
    assert updated_request.notes == "Approved with oversight"


def test_reject_request(sample_asset_with_score):
    """Test rejecting an approval request."""
    registry = get_registry()
    registry.register(sample_asset_with_score)
    
    workflow = get_approval_workflow()
    request = workflow.create_approval_request(
        asset_id="test-001",
        operation="execute",
        requester_id="user-001",
    )
    
    success = workflow.reject_request(
        request_id=request.request_id,
        approver_id="compliance-officer-001",
        reason="Insufficient justification",
    )
    
    assert success is True
    
    updated_request = workflow.get_request(request.request_id)
    assert updated_request.state == ApprovalState.REJECTED
    assert updated_request.rejection_reason == "Insufficient justification"


def test_escalate_request(sample_asset_with_score):
    """Test escalating an approval request."""
    # Create asset with medium risk
    sample_asset_with_score.risk_score.tier = RiskTier.MEDIUM
    sample_asset_with_score.risk_score.score = 45.0
    
    registry = get_registry()
    registry.register(sample_asset_with_score)
    
    workflow = get_approval_workflow()
    request = workflow.create_approval_request(
        asset_id="test-001",
        operation="execute",
        requester_id="user-001",
    )
    
    # Should require Admin
    assert request.required_approver_level == AuthorityLevel.ADMIN
    
    # Escalate
    success = workflow.escalate_request(
        request_id=request.request_id,
        escalated_by="admin-001",
        reason="Requires higher authority review",
    )
    
    assert success is True
    
    updated_request = workflow.get_request(request.request_id)
    assert updated_request.state == ApprovalState.PENDING  # Reset to pending
    assert updated_request.required_approver_level == AuthorityLevel.COMPLIANCE_OFFICER


def test_approve_non_pending_request(sample_asset_with_score):
    """Test approving a non-pending request fails."""
    registry = get_registry()
    registry.register(sample_asset_with_score)
    
    workflow = get_approval_workflow()
    request = workflow.create_approval_request(
        asset_id="test-001",
        operation="execute",
        requester_id="user-001",
    )
    
    # Approve once
    workflow.approve_request(
        request_id=request.request_id,
        approver_id="compliance-officer-001",
    )
    
    # Try to approve again
    with pytest.raises(ValueError, match="not pending"):
        workflow.approve_request(
            request_id=request.request_id,
            approver_id="compliance-officer-002",
        )


# ============================================================================
# Request Retrieval Tests
# ============================================================================

def test_get_request(sample_asset_with_score):
    """Test getting an approval request."""
    registry = get_registry()
    registry.register(sample_asset_with_score)
    
    workflow = get_approval_workflow()
    request = workflow.create_approval_request(
        asset_id="test-001",
        operation="execute",
        requester_id="user-001",
    )
    
    retrieved = workflow.get_request(request.request_id)
    
    assert retrieved is not None
    assert retrieved.request_id == request.request_id


def test_get_pending_requests(sample_asset_with_score):
    """Test getting pending approval requests."""
    registry = get_registry()
    registry.register(sample_asset_with_score)
    
    workflow = get_approval_workflow()
    
    # Create multiple requests
    request1 = workflow.create_approval_request(
        asset_id="test-001",
        operation="execute",
        requester_id="user-001",
    )
    
    request2 = workflow.create_approval_request(
        asset_id="test-001",
        operation="modify",
        requester_id="user-002",
    )
    
    # Approve one
    workflow.approve_request(
        request_id=request1.request_id,
        approver_id="compliance-officer-001",
    )
    
    # Get pending
    pending = workflow.get_pending_requests()
    
    assert len(pending) == 1
    assert pending[0].request_id == request2.request_id


def test_get_pending_requests_by_authority_level(sample_asset_with_score):
    """Test filtering pending requests by authority level."""
    registry = get_registry()
    registry.register(sample_asset_with_score)
    
    workflow = get_approval_workflow()
    request = workflow.create_approval_request(
        asset_id="test-001",
        operation="execute",
        requester_id="user-001",
    )
    
    # Should be visible to compliance officer
    pending_co = workflow.get_pending_requests(approver_level=AuthorityLevel.COMPLIANCE_OFFICER)
    assert len(pending_co) == 1
    
    # Should not be visible to operator
    pending_op = workflow.get_pending_requests(approver_level=AuthorityLevel.OPERATOR)
    assert len(pending_op) == 0


def test_get_approval_history(sample_asset_with_score):
    """Test getting approval history for an asset."""
    registry = get_registry()
    registry.register(sample_asset_with_score)
    
    workflow = get_approval_workflow()
    
    # Create multiple requests
    workflow.create_approval_request(
        asset_id="test-001",
        operation="execute",
        requester_id="user-001",
    )
    
    workflow.create_approval_request(
        asset_id="test-001",
        operation="modify",
        requester_id="user-002",
    )
    
    history = workflow.get_approval_history("test-001")
    
    assert len(history) == 2


# ============================================================================
# Approval Check Tests
# ============================================================================

def test_check_approval_required_minimal():
    """Test checking if approval required for minimal risk."""
    asset = AIAsset(
        asset_id="minimal-001",
        asset_type=AssetType.AGENT,
        name="Minimal Agent",
        description="Test",
        owner="test",
        status=AssetStatus.ACTIVE,
        tags=[],
        metadata={},
    )
    asset.risk_score = RiskScore(
        asset_id="minimal-001",
        score=10.0,
        tier=RiskTier.MINIMAL,
        breakdown={},
        calculated_at=datetime.utcnow(),
        calculated_by="test",
    )
    
    registry = get_registry()
    registry.register(asset)
    
    workflow = get_approval_workflow()
    required, tier = workflow.check_approval_required("minimal-001", "execute")
    
    assert required is False
    assert tier == RiskTier.MINIMAL


def test_check_approval_required_high():
    """Test checking if approval required for high risk."""
    asset = AIAsset(
        asset_id="high-001",
        asset_type=AssetType.AGENT,
        name="High Risk Agent",
        description="Test",
        owner="test",
        status=AssetStatus.ACTIVE,
        tags=[],
        metadata={},
    )
    asset.risk_score = RiskScore(
        asset_id="high-001",
        score=65.0,
        tier=RiskTier.HIGH,
        breakdown={},
        calculated_at=datetime.utcnow(),
        calculated_by="test",
    )
    
    registry = get_registry()
    registry.register(asset)
    
    workflow = get_approval_workflow()
    required, tier = workflow.check_approval_required("high-001", "execute")
    
    assert required is True
    assert tier == RiskTier.HIGH


# ============================================================================
# Execution Tests
# ============================================================================

def test_mark_executed(sample_asset_with_score):
    """Test marking an approved request as executed."""
    registry = get_registry()
    registry.register(sample_asset_with_score)
    
    workflow = get_approval_workflow()
    request = workflow.create_approval_request(
        asset_id="test-001",
        operation="execute",
        requester_id="user-001",
    )
    
    # Approve
    workflow.approve_request(
        request_id=request.request_id,
        approver_id="compliance-officer-001",
    )
    
    # Mark executed
    success = workflow.mark_executed(request.request_id)
    
    assert success is True
    
    updated_request = workflow.get_request(request.request_id)
    assert updated_request.state == ApprovalState.EXECUTED


def test_mark_executed_not_approved(sample_asset_with_score):
    """Test marking a non-approved request as executed fails."""
    registry = get_registry()
    registry.register(sample_asset_with_score)
    
    workflow = get_approval_workflow()
    request = workflow.create_approval_request(
        asset_id="test-001",
        operation="execute",
        requester_id="user-001",
    )
    
    # Try to mark executed without approval
    success = workflow.mark_executed(request.request_id)
    
    assert success is False


# ============================================================================
# Expiration Tests
# ============================================================================

def test_request_expiration(sample_asset_with_score):
    """Test request expiration."""
    registry = get_registry()
    registry.register(sample_asset_with_score)
    
    workflow = get_approval_workflow()
    request = workflow.create_approval_request(
        asset_id="test-001",
        operation="execute",
        requester_id="user-001",
    )
    
    # Manually expire
    request.expires_at = datetime.utcnow() - timedelta(hours=1)
    
    assert request.is_expired() is True


def test_process_expired_requests_critical(sample_asset_with_score):
    """Test processing expired critical risk requests."""
    sample_asset_with_score.risk_score.tier = RiskTier.CRITICAL
    sample_asset_with_score.risk_score.score = 85.0
    
    registry = get_registry()
    registry.register(sample_asset_with_score)
    
    workflow = get_approval_workflow()
    request = workflow.create_approval_request(
        asset_id="test-001",
        operation="execute",
        requester_id="user-001",
    )
    
    # Manually expire
    request.expires_at = datetime.utcnow() - timedelta(hours=1)
    
    # Process expired
    processed = workflow.process_expired_requests()
    
    assert len(processed) == 1
    assert processed[0].state == ApprovalState.EXPIRED
    assert "expired" in processed[0].rejection_reason.lower()


def test_singleton_instance():
    """Test that approval workflow is a singleton."""
    workflow1 = get_approval_workflow()
    workflow2 = get_approval_workflow()
    
    assert workflow1 is workflow2
